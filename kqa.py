#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pymongo
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import openai

class KQADatabase(object):
    def __init__(self, mongo_url):
        # 获得MongoDB客户端
        self.mongo_cli = pymongo.MongoClient(mongo_url)
        # 获取MongoDB数据库
        self.mongo_db = self.mongo_cli['KQA']
        # 获取用户集合
        self.user_col = self.mongo_db['users']
        # 获取文件集合
        # self.file_col = self.mongo_db['files']
        
    """
    users集合的文档: 
    _id域，name域, pwd_hash域，prompt域
    """
    def insert_user(self, name="", pwd="", \
                    prompt=""):
        # 先保证名称没注册过
        if not name or self.user_exist(name) or not pwd:
            return None
        # 再插入新的用户记录
        pwd_hash = generate_password_hash(pwd)
        doc = {'name':name, 'pwd_hash':pwd_hash, 'prompt':prompt}
        res = self.user_col.insert_one(doc)
        # res.inserted_id是ObjectId类型
        # ObjectId->String: sid = str(uid)
        # String->ObjectId: uid = ObjectId(sid)
        uid = str(res.inserted_id)
        return uid 

    def find_user(self, name="", uid=""):
        if not name and not uid:
            return None
        query = {}
        if name:
            query['name'] = name
        if uid:
            query['_id'] = ObjectId(uid)
        result = list(self.user_col.find(query))
        if result == []:
            return None
        doc = result[0]
        doc['uid'] = str(doc['_id'])
        return doc
            
    def user_exist(self, name="", uid=""):
        return (self.find_user(name, uid) != None)
    
    def validate_user(self, name="", pwd=""):
        if not name and not pwd:
            return False    # 姓名或密码为空
        user = self.find_user(name)
        if not user:
            return False    # 姓名不存在
        return check_password_hash(user['pwd_hash'], pwd)

    def update_user(self, name="", uid="", prompt=""):
        user = self.find_user(name, uid)
        if not user:
            return
        query = {}
        if name:
            query['name'] = name
        if uid:
            query['_id'] = ObjectId(uid)
        update = {"$set": {'prompt':prompt,}}
        self.user_col.update_one(query, update)
        return 
    
    """
    files集合的文档: 
    _id域，name域, title域，paragraphs域
    """
    # def insert_file(self, name:str="", title:str="", \
    #                 paragraphs:list[str]=[]) -> str:
    #     if not name or not title or not paragraphs:
    #         return None
    #     # 已经存在就更新paragraphs
    #     if self.file_exist(name, title):
    #         print("insert_file: update")
    #         query = {'name':name, 'title':title}
    #         update = {"$set": {'paragraphs':paragraphs,}}
    #         self.file_col.update_one(query, update)
    #         return None
    #     # 不存在才新增doc
    #     print("insert_file: insert")
    #     doc = {'name':name, 'title':title, \
    #                    'paragraphs':paragraphs}
    #     res = self.file_col.insert_one(doc)
    #     uid = str(res.inserted_id)
    #     return uid
    
    # def find_files_by_user(self, name:str="") -> list:
    #     if not name:
    #         return []
    #     query = {'name':name}
    #     results = list(self.file_col.find(query))
    #     # result可能为[]
    #     return results

    # def find_file(self, name:str="", title:str="") -> dict:
    #     if not name or not title:
    #         return None
    #     query = {'name':name, 'title':title}
    #     result = list(self.file_col.find(query))
    #     if result == []:
    #         return None
    #     doc = result[0]
    #     return doc
    
    # def file_exist(self, name:str="", title:str="") -> bool:
    #     return (self.find_file(name, title) != None)

    # def delete_file(self, name:str="", title:str=""):
    #     if not name or not title:
    #         return
    #     query = {'name':name, 'title':title}
    #     self.file_col.delete_one(query)
    #     return

class KQALangModel(object):
    def __init__(self, openai_api_key, openai_model):
        # 设置openai的api key
        openai.api_key = openai_api_key
        # openai_model是"gpt-3.5-turbo"或"gpt-4"
        self.openai_model = openai_model
    
    def answer(self, messages):
        err_msg = ""
        try:
            #Make your OpenAI API request here
            completion = openai.ChatCompletion.create(
                                        model=self.openai_model,
                                        messages=messages,
                                        temperature=0.6,
                                        max_tokens=2048) 
        except openai.error.APIError as e:
            #Handle API error here, e.g. retry or log
            err_msg = "OpenAI API调用出错"
            print(f"OpenAI API returned an API Error: {e}")
            pass    # 忽略异常，继续执行。
        except openai.error.APIConnectionError as e:
            #Handle connection error here
            err_msg = "OpenAI API连接失败"
            print(f"Failed to connect to OpenAI API: {e}")
            pass
        except openai.error.RateLimitError as e:
            #Handle rate limit error (we recommend using exponential backoff)
            err_msg = "OpenAI API频繁访问"
            print(f"OpenAI API request exceeded rate limit: {e}")
            pass
        if err_msg != "":
            return (False, err_msg)
        if not(completion and 'choices' in completion \
            and len(completion['choices']) > 0 \
            and 'message' in completion['choices'][0] \
            and 'content' in completion['choices'][0]['message']):
            err_msg = "OpenAI API格式错误"
            print(f"OpenAI API return format error: completion={completion}")
            return (False, err_msg)
        chat_answer = completion.choices[0].message.content
        return (True, chat_answer)