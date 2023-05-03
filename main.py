#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, datetime, json
from flask import Flask, request, redirect, url_for, render_template, session
from unstructured.partition.doc import partition_doc
from unstructured.partition.docx import partition_docx
#import requests
#from bs4 import BeautifulSoup
from kqa import KQALangModel, KQADatabase

# 获取全局变量
if os.getenv("DEPLOY_ON_RAILWAY"):
    # 在railway部署：从系统中获取环境变量
    PORT = os.getenv("PORT")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL")
    MONGO_URL = os.getenv("MONGO_URL")
else:
    # 在本地部署：读取配置文件中的变量
    with open("./config.json", encoding='utf-8') as config_fid:
        config = json.load(config_fid)  # 读取配置文件
    PORT = config["PORT"]
    OPENAI_API_KEY = config["OPENAI_API_KEY"]
    OPENAI_MODEL = config["OPENAI_MODEL"]
    MONGO_URL = config['MONGO_URL']
    os.environ['HTTP_PROXY'] = config['HTTP_PROXY']
    os.environ['HTTPS_PROXY'] = config['HTTPS_PROXY']
print("================")
print(f'PORT={PORT}')
print(f'OPENAI_API_KEY={OPENAI_API_KEY}')
print(f'OPENAI_MODEL={OPENAI_MODEL}')
print(f'MONGO_URL={MONGO_URL}')
print("================")

# 创建Flask应用
app = Flask(__name__)
# 密钥用来加密session到浏览器的cookie中
# 等价于 app.secret_key = "who dares win"
app.config['SECRET_KEY'] = "who dares win"
# session保存时长为1天
# 等价于app.permanent_session_lifetime = datetime.timedelta(days=1) 
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=1)
# 限制上传文件不超过16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  

# 创建语言模型
lang_model = KQALangModel(OPENAI_API_KEY, OPENAI_MODEL)

# 创建数据库
db = KQADatabase(MONGO_URL)

@app.route('/') # 默认methods=['GET']
def index():
    # state in ['register', 'login', 'prompt', 'chat']
    # 登录阶段：没有登录，要先登录。
    state = 'login'
    if ('name' in session) and ('uid' in session) and \
        db.user_exist(name=session['name'], uid=session['uid']):
        # 提示阶段：已经登录，没有提示。
        state = 'prompt'
        if ("prompt" in session) and ("messages" in session):
            # 交互阶段：已有提示，进入问答。
            state = 'chat'  
    print(f"主页: state={state}")
    return render_template('index.html', state=state)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('index.html', state='register')
        
    assert(request.method == 'POST')
    # 用户信息
    name = request.form.get('name')
    pwd = request.form.get('pwd')
    pwd2 = request.form.get('pwd2')
    # 验证输入
    if (not pwd) or (not pwd2) or (pwd != pwd2):
        return render_template('index.html', \
                    state='register', auth_msg="密码错误")
    if (not name) or (not re.match("^[A-Za-z]+[A-Za-z0-9_]*$", name)):
        return render_template('index.html', \
                    state='register', auth_msg="名称错误")       
    # 新增用户
    uid = db.insert_user(name=name, pwd=pwd) 
    if not uid:
        return render_template('index.html', \
                    state='register', auth_msg="账号存在") 
    print(f"注册: name={name}, uid={uid}")
    return render_template('index.html', \
                    state='login', auth_msg="注册成功")

@app.route('/login', methods=['POST'])
def login():
    # 用户信息
    name = request.form.get('name')
    pwd = request.form.get('pwd')
    # 验证输入
    if (not pwd) or (not name) \
            or (not re.match("^[A-Za-z]+[A-Za-z0-9_]*$", name)):
        return render_template('index.html', \
                    state='login', auth_msg="输入错误")
    # 查询记录
    if not db.validate_user(name, pwd):
        return render_template('index.html', \
                    state='login', auth_msg="登录失败")
    # 写入会话：相当于登录成功。
    user = db.find_user(name)
    session['name'] = user['name']
    session['uid'] = user['uid']
    if 'prompt' in user and user['prompt'] != "":
        session['prompt'] = user['prompt']
        messages = [{"role": "system", "content": user['prompt']}]
        session['messages'] = messages
    titles = [f['title'] for f in db.find_files_by_user(name)]
    session['titles'] = titles
    print(f"登录: name={name}, uid={session['uid']}")
    return redirect(url_for('index'))

@app.route('/logout', methods=['POST'])
def logout():
    name = session.get('name')
    uid = session.get('uid')
    if name and uid:
        print(f"登出: name={name}, uid={uid}")
    # 清空会话：相当于登出成功。
    ## 不能用del session['xxx']，不存在时会异常。
    #session.pop('name', None) 
    #session.pop('uid', None)
    #session.pop('prompt', None)
    #session.pop('messages', None)
    session.clear()
    return redirect(url_for('index'))    

@app.route('/upload', methods=['POST'])
def upload():
    submit = request.form.get('submit')
    if submit == '上传':
        if 'file' not in request.files:
            return redirect(url_for('index'))
        # 从文件中提取title和paragraphs
        file = request.files['file']
        filename, filetype = os.path.splitext(file.filename)
        title = filename.strip()
        filetype = filetype.lower()
        if filetype not in ['.txt', '.doc', '.docx']:
            # 永不进入：form要求是3种文件类型中的一种。
            return redirect(url_for('index')) 
        filepath = "./tmp" # 保存到临时文件中
        file.save(filepath)
        if filetype == '.txt':
            with open(filepath, "r") as f:
                paragraphs = f.readlines()
        elif filetype == '.doc':
            paragraphs = partition_doc(filename=filepath)
        elif filetype == '.docx':
            paragraphs = partition_docx(filename=filepath)
        paragraphs = [str(p).strip() for p in paragraphs \
                                      if str(p).strip() != ""]
        # 新增文件
        uid = db.insert_file(name=session['name'], title=title, \
                                       paragraphs=paragraphs)
        if uid != None:
            titles = session['titles']
            titles.append(title)
            session['titles'] = titles
        print(f"上传: title={title}")
        # print("paragraphs:")
        # for i, p in enumerate(paragraphs):
        #     print(f"[{i}]{p}")
        return redirect(url_for('index'))
    # elif submit == '抓取':    
    #     # 下载网页
    #     url = request.form.get('url')
    #     response = requests.get(url=url)
    #     # 从网页中提取title和paragraphs
    #     charset = requests.utils.get_encodings_from_content(response.text)[0]
    #     soup = BeautifulSoup( \
    #         response.text.encode(response.encoding).decode(charset), \
    #         'html.parser', from_encoding=charset)
    #     result = soup.find('h1')
    #     if result:
    #         title = result.text
    #     else:
    #         result = soup.find('h2')
    #         if result:
    #             title = result.text
    #         else:
    #             title = soup.find('title').text
    #     title = title.strip()
    #     paragraphs = []
    #     for p in soup.find_all('p'):
    #         if p.text.strip() != "":
    #             paragraphs.append(p.text.strip())
    #     # 新增文件
    #     uid = db.insert_file(name=session['name'], title=title, \
    #                                    paragraphs=paragraphs)
    #     if uid != None:
    #         titles = session['titles']
    #         titles.append(title)
    #         session['titles'] = titles
    #     print(f"抓取: title={title}")
    #     # print("paragraphs:")
    #     # for i, p in enumerate(paragraphs):
    #     #     print("f[{i}]{p}")
    #     return redirect(url_for('index'))
    elif submit == '删除': 
        title_idx = request.form.get('title_idx')
        title_idx = int(title_idx)
        if 'titles' not in session or 'name' not in session:
            return redirect(url_for('index'))
        # 删除文件
        title = session['titles'][title_idx]
        titles = session['titles']
        titles.pop(title_idx)
        session['titles'] = titles
        db.delete_file(name=session['name'], title=title)
        print(f"删文: title={title}")
        return redirect(url_for('index'))
    else:
        return redirect(url_for('index'))

@app.route('/prompt', methods=['POST'])
def prompt():
    submit = request.form.get('submit')
    if submit == '提交':
        # 写入问答会话
        prompt = request.form.get('prompt')
        if prompt == "":
            return render_template('index.html', \
                        state='prompt', prompt_msg="提示不能为空")
        messages = [{"role": "system", "content": prompt}]
        session['prompt'] = prompt
        session['messages'] = messages
        # 保存prompt到数据库中
        db.update_user(name=session['name'], uid=session['uid'], \
                       prompt=session["prompt"])
        print(f"提示：prompt={prompt}, messages={messages}")
        return redirect(url_for('index'))
    elif submit == '重来':
        # 清空问答会话
        print(f"重来: prompt={session.get('prompt')}")
        session.pop('prompt', None)
        session.pop('messages', None)
        # 清除数据库中的prompt
        db.update_user(name=session['name'], uid=session['uid'], prompt="")
        return redirect(url_for('index'))
    return redirect(url_for('index'))
        
@app.route('/chat', methods=['POST'])
def chat():
    submit = request.form.get('submit')
    if submit == '发送':
        # 问答服务
        chat_ask = request.form.get('chat_ask')
        if 'messages' not in session:
            return redirect(url_for('index'))
        messages = session['messages']
        messages.append({"role":"user", "content":chat_ask})
        is_ok, result = lang_model.answer(messages)
        # 回答失败
        if not is_ok:
            err_msg = result
            return render_template('index.html', \
                                   state='chat', chat_msg=err_msg)
        # 回答成功
        chat_answer = result
        messages.append({"role":"assistant", "content":chat_answer})
        session['messages']=messages
        print(f"问答: chat_ask={chat_ask}, chat_answer={chat_answer}")
        return redirect(url_for('index'))
    elif submit == '删除':
        # message_idx为某轮问答的发问对应的messages索引
        message_idx = request.form.get('message_idx')
        message_idx = int(message_idx)
        # message_idx对应发问的下标，应该是奇数。
        if ('messages' not in session) or (message_idx % 2 == 0):
            return redirect(url_for('index'))
        messages = session['messages']
        old_len = len(messages)
        # 删除message_idx和message_idx之后的所有问答
        messages = messages[:message_idx]
        session['messages'] = messages
        new_len = len(messages)
        print(f"删除: len(old_messages)={old_len}, len(new_messages)={new_len}")
        return redirect(url_for('index'))
    return redirect(url_for('index'))
 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
    
    