#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# KQA: Knowledge Question Answering
import re
import numpy as np
import pymongo
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import openai
import tiktoken
import pinecone
from serpapi import GoogleSearch
import chromadb
from chromadb.utils import embedding_functions


class MongoDB(object):
    def __init__(self, mongo_url):
        # 获得MongoDB客户端
        self.mongo_cli = pymongo.MongoClient(mongo_url)
        # 获取MongoDB数据库
        self.mongo_db = self.mongo_cli['KQA']
        # 获取用户集合
        self.user_col = self.mongo_db['users']
        # 获取文件集合
        self.file_col = self.mongo_db['files']
        
    """
    users集合：存储每个用户的个人信息 
    user文档：_id域，name域, pwd_hash域，prompt域
    """
    def insert_user(self, name="", pwd="", prompt=""):
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
    files集合：存储每个文件的文本信息 
    file文档：_id域，name域, title域，paragraphs域
    """
    def insert_file(self, name="", title="", paragraphs=[], chunks=[]):
        if not name or not title or not paragraphs or not chunks:
            return None
        # 已经存在就先删掉
        if self.file_exist(name, title):
            self.delete_file(name=name, title=title)
        # 新增文件记录
        doc = {'name':name, 'title':title, \
               'paragraphs':paragraphs, 'chunks':chunks}
        res = self.file_col.insert_one(doc)
        file_id = str(res.inserted_id)
        return file_id
    
    def update_file(self, name="", title="", paragraphs=[], chunks=[]):
        if not name or not title or not paragraphs or not chunks:
            return None
        # 先保证已经存在
        if not self.file_exist(name, title):
            return None
        # 再更新文件记录
        query = {'name':name, 'title':title}
        update = {"$set": {'paragraphs':paragraphs, 'chunks':chunks}}
        res = self.file_col.update_one(query, update)
        #匹配query的就只有一个：res.matched_count == 1
        #res.modified_count为1表示paragraphs已修改，为0表示内容没修改。
        return res.modified_count
    
    def find_files_by_user(self, name=""):
        if not name:
            return []
        query = {'name':name}
        results = list(self.file_col.find(query))
        # result可能为[]
        return results

    def find_file(self, name="", title="", file_id=""):
        if not ((name and title) or (name and file_id)):
            return None
        query = {'name':name}
        if title:
            query['title'] = title
        if file_id:
            query['_id'] = ObjectId(file_id)
        result = list(self.file_col.find(query))
        if result == []:
            return None
        doc = result[0]
        doc['fid'] = str(doc['_id'])
        return doc
    
    def file_exist(self, name="", title=""):
        return (self.find_file(name, title) != None)

    def delete_file(self, name="", title=""):
        if not name or not title:
            return
        query = {'name':name, 'title':title}
        self.file_col.delete_one(query)
        return


class OpenAI(object):
    MIN_TOKENS = 256     # 每个chunk的最小token数
    MIDDLE_TOKENS = 384  # 每个chunk的期望token数
    MAX_TOKENS = 512     # 每个chunk的最大token数
    
    def __init__(self, openai_api_key, \
                 openai_chat_model, openai_embed_model):
        # 设置openai的api key
        openai.api_key = openai_api_key
        # chat_model"gpt-3.5-turbo"或"gpt-4"
        self.chat_model = openai_chat_model
        self.embed_model = openai_embed_model
        # cl100k_base编码用在gpt-4、gpt-3.5-turbo、text-embedding-ada-002上
        # self.encoding = tiktoken.encoding_for_model("gpt-4")
        # self.encoding = tiktoken.encoding_for_model("text-embedding-ada-002")
        self.encoding = tiktoken.get_encoding("cl100k_base")
    
    """
    chat模型：OpenAI的chatgpt或gpt4
    """
    def answer_question(self, messages):
        err_msg = ""
        try:
            #Make your OpenAI API request here
            completion = openai.ChatCompletion.create(
                                        model=self.chat_model,
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
        answer = completion.choices[0].message.content
        return (True, answer)
    
    """
    embedding模型：OpenAI的text-embedding-ada-002
    """
    # 嵌入query
    def embed_query(self, query):
        result = openai.Embedding.create(input=query, \
                                         model=self.embed_model)
        embedding = result['data'][0]['embedding']
        return embedding
    
    # 嵌入document
    def embed_document(self, paragraphs):
        chunks = []
        for paragraph in paragraphs:
            num_tokens = len(self.encoding.encode(paragraph))
            if num_tokens < self.MAX_TOKENS:
                chunks.append(paragraph)
            else:
                paragraph_chunks = self.split_paragraph(paragraph)
                chunks.extend(paragraph_chunks)
        new_chunks = self.merge_chunks(chunks)
        if len(new_chunks) == 0:
            return ([], [])
        result = openai.Embedding.create(input=new_chunks, \
                                         model=self.embed_model)
        embeddings = [item['embedding'] for item in result['data']]
        return (new_chunks, embeddings)
        
    # 合并区块：有重叠部分
    def merge_chunks(self, chunks):
        if len(chunks) == 0:
            return []
        # 尽量让每个chunk的token数接近并<= MIDDEL_TOKENS
        new_chunks = []
        chunk = chunks[0]
        for i in range(1, len(chunks)):
            if len(chunk) + len(chunks[i]) < self.MIN_TOKENS:
                chunk += chunks[i]
                if i == len(chunks) - 1:
                    # 如果不超过MAX_TOKENS，可以合并最后两个新的chunk
                    if len(new_chunks) > 0 and \
                        len(new_chunks[-1][0])+ len(chunk) < self.MAX_TOKENS:
                        new_chunks[-1][1] = chunk
                    else: # 几乎不进来：前一个chunk略>256，后一个chunk<256
                        new_chunks.append([chunk, ""]) # overlap为""
            else:
                is_ended = False
                # 让前后两个chunk的重叠token数为MIDDLE_TOKENS - MIN_TOKENS
                # 也就是说chunk和overlap的token数接近并 <= MIDDLE_TOKENS
                overlap = ""
                for j in range(i, len(chunks)):
                    if len(chunk) + len(overlap) + len(chunks[j]) \
                            < self.MIDDLE_TOKENS:
                        overlap += chunks[j]
                        if j == len(chunks) - 1:
                            is_ended = True
                    else:
                        break
                new_chunks.append([chunk, overlap])
                chunk = chunks[i]
                if is_ended:
                    break;
        new_chunks = [new_chunks[i][0] + new_chunks[i][1] \
                              for i in range(len(new_chunks))]
        return new_chunks
                
    # 合并句子：没有重叠部分
    def merge_sentences(self, sentences, num_chunks):
        data = openai.Embedding.create(input=sentences, \
                        model=self.embed_model)['data']
        # data[i]['embedding']类型为python list，需要转为numpy array
        embeddings = [np.array(item['embedding']) for item in data]
        num_tokens = [len(self.encoding.encode(s)) for s in sentences]
        chunks = [{'text':sentences[i], 'embedding':embeddings[i],\
                   'num_tokens':num_tokens[i], 'num_sentences':1} \
                  for i in range(len(sentences))]
        while len(chunks) > num_chunks:
            max_lhs = 0
            max_dot_product = chunks[0]['embedding'].dot(chunks[1]['embedding'])
            for lhs in range(1, len(chunks) - 1): # rhs = lhs + 1
                dot_product = chunks[lhs]['embedding'].dot(\
                                    chunks[lhs+1]['embedding'])
                merged_tokens = chunks[lhs]['num_tokens'] + \
                                chunks[lhs+1]['num_tokens']
                if max_dot_product < dot_product \
                        and merged_tokens < self.MAX_TOKENS:
                    max_lhs = lhs
                    max_dot_product = dot_product
            chunks[max_lhs]['text'] += chunks[max_lhs+1]['text']
            chunks[max_lhs]['embeddings'] = \
        (chunks[max_lhs]['embedding'] * chunks[max_lhs]['num_sentences'] +\
         chunks[max_lhs+1]['embedding'] * chunks[max_lhs+1]['num_sentences']) /\
        (chunks[max_lhs]['num_sentences'] + chunks[max_lhs+1]['num_sentences'])
            chunks[max_lhs]['num_tokens'] += chunks[max_lhs+1]['num_tokens']
            chunks[max_lhs]['num_sentences'] += chunks[max_lhs+1]['num_sentences']
            chunks.pop(max_lhs+1)
        chunks = [chunks[i]['text'] for i in range(len(chunks))]
        return chunks
    
    # 分割段落：段落 -> 句子s -> 区块s
    def split_paragraph(self, paragraph):
        num_tokens = len(self.encoding.encode(paragraph))
        if num_tokens < self.MAX_TOKENS:
            chunks = [paragraph,]
            return chunks
        
        # num_tokens >= MAX_TOKENS
        # 划分段落为句子：paragraph -> sentences
        sentences = re.split("(\.|\!|\?|。|？|！)", paragraph)
        sentences = [sentences[2*i] + sentences[2*i+1] \
                     for i in range(int(len(sentences)/2))]
        # num_chunks为chunk数，至少>=2
        num_chunks = num_tokens // self.MIN_TOKENS 
        if len(sentences) <= num_chunks: # 增加逗号、分号和冒号
            sentences = re.split(\
                        "(\,|\;|\:|\.|\!|\?|，|；|：|。|？|！)", paragraph)
            sentences = [sentences[2*i] + sentences[2*i+1] \
                         for i in range(int(len(sentences)/2))]
        if len(sentences) <= num_chunks:
            chunk_length = int(len(paragraph) / (num_chunks+1))
            chunks = []
            for i in range(num_chunks+1):
                chunks.append(paragraph[i*chunk_length, (i+1)*chunk_length])
            return chunks
        
        # len(sentences) > num_chunks
        # 合并句子为区块：sentences -> chunks
        chunks = self.merge_sentences(sentences, num_chunks)
        return chunks
        

class Pinecone(object):
    def __init__(self, pinecone_api_key):
        pinecone.init(api_key=pinecone_api_key, environment="us-west1-gcp-free")
        self.index_name = 'kqa'
        if self.index_name not in pinecone.list_indexes():
            # OpenAI的Embedding API的维数是1536
            pinecone.create_index(name=self.index_name, dimension=1536)
        self.index = pinecone.Index(index_name=self.index_name)
        
    @staticmethod
    def fid2eid(file_id, chunk_id):
        return file_id + ":" + str(chunk_id)
    
    @staticmethod
    def eid2fid(embed_id):
        file_id, chunk_id = embed_id.rsplit(':', 1)
        chunk_id = int(chunk_id)
        return (file_id, chunk_id)
        
    def insert(self, file_id="", embeddings=[], namespace=''):
        if not file_id or not embeddings or not namespace:
            return
        vectors = []
        for chunk_id in range(len(embeddings)):
            embed_id = self.fid2eid(file_id, chunk_id)
            vectors.append((embed_id, embeddings[chunk_id]))
        response = self.index.upsert(vectors=vectors, namespace=namespace)
        return response.upserted_count
    
    def query(self, query_embedding, namespace='', top_k=1):
        if not namespace:
            return None
        result = self.index.query(vector=query_embedding, \
                            namespace=namespace, top_k=top_k)
        if not result.matches:
            return None
        embed_ids = [match.id for match in result.matches]
        scores = [match.score for match in result.matches]
        n = len(result.matches)
        ids = [self.eid2fid(embed_ids[i]) for i in range(n)]
        return (scores, ids)
        
    def delete(self, file_id="", num_embeddings=0, namespace=''):
        if not file_id or not num_embeddings or not namespace:
            return
        ids = []
        for chunk_id in range(num_embeddings):
            embed_id = self.fid2eid(file_id, chunk_id)
            ids.append(embed_id)
        self.index.delete(ids=ids, namespace=namespace)
        return 
    
        
class Google(object):
    def __init__(self, serp_api_key):
        # 获得Serpapi的API KEY
        self.serp_api_key = serp_api_key
        
    def search(self, query):
        results = GoogleSearch({
                'q': query,    
                'engine': 'google',
                'api_key': self.serp_api_key,
                'google_domain': "google.com.hk",
                'hl': 'zh-CN',
                'gl': 'cn',
                'start': 0,
                'num': 10,
                'output': 'json'
            }).get_dict()
        if results["search_metadata"]['status'] == 'Error':
            return None
        # results["search_metadata"]['status'] == 'Success'
        webpages = []
        for item in results['organic_results']:
            webpages.append({'title': item['title'], 'link': item['link']})
        return webpages
    
        
class Chroma(object):
    def __init__(self, openai_api_key, openai_embed_model):
        self.client = chromadb.Client()
        # chromadb内置的OpenAI Embedding Function：之后不用的
        openai = embedding_functions.OpenAIEmbeddingFunction(\
            api_key=openai_api_key, model_name=openai_embed_model)
        # 创建集合
        #self.collection = self.client.create_collection(name='kqa')
        self.collection = self.client.get_or_create_collection(name='kqa', \
                                embedding_function=openai)
        
    def insert(self, chunks=[], embeddings=[], title='', link=''):
        if not chunks or not embeddings or not title or not link:
            return 
        # 获取集合的文档数 
        num = self.collection.count()
        ids = [str(num+i) for i in range(len(chunks))]
        metadatas = [{'title':title, 'link':link} for i in range(len(chunks))]
        # 传入embeddings参数：不会调用chromadb内置的embedding function
        self.collection.add(ids=ids, documents=chunks, \
                    embeddings=embeddings, metadatas=metadatas)
        
    def query(self, query_embedding, n_results=1):
        try:
            results = self.collection.query([query_embedding], \
                include=['documents', 'embeddings', 'metadatas', 'distances'])
        except chromadb.errors.NotEnoughElementsException as err:
            print(err)
            return None
        # results有'documents','embeddings','metadatas','distances'四个属性
        return results
            
    def clear(self):
        # 获取集合的文档数 
        num = self.collection.count()
        ids = [str(i) for i in range(num)]
        self.collection.delete(ids=ids)
        
    def __del__(self):
        # 执行del obj(或者程序结束)会触发__del__析构函数
        # 删除集合
        self.client.delete_collection(name='kqa')
        
        
        