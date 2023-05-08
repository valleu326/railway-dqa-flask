#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, datetime, json
from flask import Flask, request, redirect, url_for, render_template, session
from unstructured.partition.doc import partition_doc
from unstructured.partition.docx import partition_docx
import requests
from requests.utils import get_encoding_from_headers, get_encodings_from_content
import chardet
from bs4 import BeautifulSoup
from kqa import KQAOpenAI, KQAMongoDB, KQAPinecone
from serpapi import GoogleSearch

# 获取全局变量
if os.getenv("DEPLOY_ON_RAILWAY"):
    # 在railway部署：从系统中获取环境变量
    PORT = os.getenv("PORT")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL")
    OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL")
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    SERP_API_KEY = os.getenv("SERP_API_KEY")
    MONGO_URL = os.getenv("MONGO_URL")
else:
    # 在本地部署：读取配置文件中的变量
    with open("./config.json", encoding='utf-8') as config_fid:
        config = json.load(config_fid)  # 读取配置文件
    PORT = config["PORT"]
    OPENAI_API_KEY = config["OPENAI_API_KEY"]
    OPENAI_CHAT_MODEL = config["OPENAI_CHAT_MODEL"]
    OPENAI_EMBED_MODEL = config["OPENAI_EMBED_MODEL"]
    PINECONE_API_KEY = config["PINECONE_API_KEY"]
    SERP_API_KEY = config["SERP_API_KEY"]
    MONGO_URL = config['MONGO_URL']
    os.environ['HTTP_PROXY'] = config['HTTP_PROXY']
    os.environ['HTTPS_PROXY'] = config['HTTPS_PROXY']
print("================")
print(f'PORT={PORT}')
print(f'OPENAI_API_KEY={OPENAI_API_KEY}')
print(f'OPENAI_CHAT_MODEL={OPENAI_CHAT_MODEL}')
print(f'OPENAI_EMBED_MODEL={OPENAI_EMBED_MODEL}')
print(f'PINECONE_API_KEY={PINECONE_API_KEY}')
print(f'SERP_API_KEY={SERP_API_KEY}')
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
model = KQAOpenAI(OPENAI_API_KEY, \
        OPENAI_CHAT_MODEL, OPENAI_EMBED_MODEL)

# 创建MongoDB数据库
db = KQAMongoDB(MONGO_URL)

# 创建Pinecone数据库
pc = KQAPinecone(PINECONE_API_KEY)

@app.route('/') # 默认methods=['GET']
def index():
    # state in ['register', 'login', 'prompt', 'chat']
    state = 'login' # 登录阶段：没有登录，要先登录。
    if ('name' in session) and ('uid' in session) and \
        db.user_exist(name=session['name'], uid=session['uid']):
        state = 'prompt' # 提示阶段：已经登录，没有提示。
        if ("prompt" in session) and ("messages" in session) \
                                    and ("contexts" in session):
            state = 'chat' # 交互阶段：已有提示，进入问答。
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
        session['contexts'] = []
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
    #session.pop('contexts', None)
    session.clear()
    return redirect(url_for('index'))    

@app.route('/upload', methods=['POST'])
def upload():
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
    # 嵌入文件
    chunks, embeddings = model.embed_document(paragraphs)
    # 新增文件
    file_id = db.insert_file(name=session['name'], title=title, \
                         paragraphs=paragraphs, chunks=chunks)
    if file_id != None:
        titles = session['titles']
        titles.append(title)
        session['titles'] = titles
        # 新增嵌入
        pc.insert(file_id, embeddings)
    print(f"上传: 标题={title} 段数={len(paragraphs)}, 块数={len(chunks)}")
    return redirect(url_for('index'))

def find_encoding(response):
    encoding = None
    # Try charset from content-type
    if response.headers:
        encoding = get_encoding_from_headers(response.headers)
        if encoding == 'ISO-8859-1':
            encoding = None
    # Try charset from content
    if not encoding:
        encoding = get_encodings_from_content(response.content)
        encoding = encoding and encoding[0] or None
    # Fallback to auto-detected encoding.
    if not encoding and chardet is not None:
        encoding = chardet.detect(response.content)['encoding']
    if encoding and encoding.lower() == 'gb2312':
        encoding = 'gb18030'
    return encoding or 'latin_1'

@app.route('/crawl', methods=['POST'])
def crawl():  
    # 下载网页
    url = request.form.get('url')
    response = requests.get(url=url)
    # 从网页中提取title和paragraphs
    #charset = requests.utils.get_encodings_from_content(response.text)[0]
    charset = find_encoding(response)
    soup = BeautifulSoup( \
        response.text.encode(response.encoding).decode(charset), \
        'html.parser', from_encoding=charset)
    result = soup.find('h1')
    if result:
        title = result.text
    else:
        result = soup.find('h2')
        if result:
            title = result.text
        else:
            title = soup.find('title').text
    title = title.strip()
    paragraphs = []
    for p in soup.find_all('p'):
        if p.text.strip() != "":
            paragraphs.append(p.text.strip())
    # 嵌入文件
    chunks, embeddings = model.embed_document(paragraphs)
    # 新增文件
    file_id = db.insert_file(name=session['name'], title=title, \
                         paragraphs=paragraphs, chunks=chunks)
    if file_id != None:
        titles = session['titles']
        titles.append(title)
        session['titles'] = titles
        # 新增嵌入
        pc.insert(file_id, embeddings)
    print(f"抓取: 标题={title} 段数={len(paragraphs)}, 块数={len(chunks)}")
    return redirect(url_for('index'))

@app.route('/delete', methods=['POST'])
def delete():
    title_idx = request.form.get('title_idx')
    title_idx = int(title_idx)
    if 'titles' not in session or 'name' not in session:
        return redirect(url_for('index'))
    # 删除文件
    title = session['titles'][title_idx]
    titles = session['titles']
    titles.pop(title_idx)
    session['titles'] = titles
    file_doc = db.find_file(name=session['name'], title=title)
    file_id = file_doc['fid']
    num_chunks = len(file_doc['chunks'])
    db.delete_file(name=session['name'], title=title)
    # 删除嵌入
    pc.delete(file_id=file_id, num_embeddings=num_chunks)
    print(f"删文: title={title}")
    return redirect(url_for('index'))

@app.route('/read', methods=['GET'])
def read():
    title_idx = request.args.get('title_idx')
    title_idx = int(title_idx)
    if 'titles' not in session or 'name' not in session:
        return redirect(url_for('index'))
    # 删除文件
    title = session['titles'][title_idx]
    file_doc = db.find_file(name=session['name'], title=title)
    paragraphs = file_doc['paragraphs']
    chunks = file_doc['chunks']
    print(f"读文: title={title}")
    return render_template('read.html', title=title, \
                    paragraphs=paragraphs, chunks=chunks)

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
        contexts = []
        session['prompt'] = prompt
        session['messages'] = messages
        session['contexts'] = contexts
        # 保存prompt到数据库中
        db.update_user(name=session['name'], uid=session['uid'], \
                       prompt=session["prompt"])
        print(f"提示：prompt={prompt}, messages={messages}, contexts={contexts}")
        return redirect(url_for('index'))
    elif submit == '重来':
        # 清空问答会话
        print(f"重来: prompt={session.get('prompt')}")
        session.pop('prompt', None)
        session.pop('messages', None)
        session.pop('contexts', None)
        # 清除数据库中的prompt
        db.update_user(name=session['name'], uid=session['uid'], prompt="")
        return redirect(url_for('index'))
    return redirect(url_for('index'))
        
@app.route('/chat', methods=['POST'])
def chat():
    submit = request.form.get('submit')
    if submit == '发送':
        # 问答服务
        question = request.form.get('question')
        if 'messages' not in session or 'contexts' not in session:
            return redirect(url_for('index'))
        messages = session['messages']
        contexts = session['contexts']
        question_embedding = model.embed_query(query=question)
        fid_and_cid_list = pc.query(query_embedding=question_embedding)
        file_id, chunk_id = fid_and_cid_list[0]
        file_doc = db.find_file(name=session['name'], file_id=file_id)
        context = file_doc['chunks'][chunk_id]
        contexted_question = "根据以下内容回答问题：\n内容：" \
                                + context + "\n问题：" + question
        messages.append({"role":"user", "content":contexted_question})
        okey, result = model.qa(messages)
        messages.pop(-1)
        # 回答失败
        if not okey:
            err_msg = result
            return render_template('index.html', \
                                   state='chat', chat_msg=err_msg)
        # 回答成功
        answer = result
        messages.append({"role":"user", "content":question})
        messages.append({"role":"assistant", "content":answer})
        session['messages']=messages
        contexts.append(context)
        session['contexts']=contexts
        print(f"问答: question={question}, context={context}, answer={answer}")
        return redirect(url_for('index'))
    elif submit == '删除':
        # message_idx为某轮问答的发问对应的messages索引
        message_idx = request.form.get('message_idx')
        message_idx = int(message_idx)
        # message_idx对应发问的下标，应该是奇数。
        if ('messages' not in session) or (message_idx % 2 == 0):
            return redirect(url_for('index'))
        messages = session['messages']
        contexts = session['contexts']
        # 删除message_idx和message_idx之后的所有问答
        messages = messages[:message_idx]
        session['messages'] = messages
        contexts = contexts[:int((message_idx-1)/2)]
        session['contexts'] = contexts
        print(f"删话: len(messages)={len(messages)}, "
                      + f"len(contexts)={len(contexts)}")
        return redirect(url_for('index'))
    return redirect(url_for('index'))
 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
    
    