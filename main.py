from flask import Flask, request, redirect, url_for, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash
import openai
import os
import re
import datetime
import json
import logging


# 日志基本配置
logging.basicConfig(filename='./logging.txt', 
                    filemode='a',       # 'w'为覆盖，'a'为追加
                    format="%(asctime)s [%(levelname)s] %(message)s ",
                    level=logging.DEBUG # 只打印level及level以上的消息
                    )
# 读取配置文件
with open("./config.json", encoding='utf-8') as f:
    config = json.load(f)

# 首先从系统中获取环境变量，没有再去取配置文件中的相应变量
PORT = os.getenv("PORT", default=config['PORT'])
API_KEY = os.getenv("OPENAI_API_KEY", default=config['OPENAI_API_KEY'])
openai.api_key = API_KEY
MODEL = os.getenv("OPENAI_MODEL", default=config['OPENAI_MODEL'])
#HTTP_PROXY = os.getenv("HTTP_PROXY", default=config['HTTP_PROXY'])
#os.environ['HTTP_PROXY'] = HTTP_PROXY
#HTTPS_PROXY = os.getenv("HTTPS_PROXY", default=config['HTTPS_PROXY'])
#os.environ['HTTPS_PROXY'] = HTTPS_PROXY
logging.debug(f'PORT = {PORT}')
logging.debug(f'API_KEY ={API_KEY}')
logging.debug(f'MODEL ={MODEL}')
#logging.debug(f'HTTP_PROXY ={HTTP_PROXY}')
#logging.debug(f'HTTPS_PROXY ={HTTPS_PROXY}')


# 提示语集
with open("./prompts.json", encoding='utf-8') as f:
    prompts = json.load(f)

# 创建Flask应用
app = Flask(__name__)
# 密钥用来加密session到浏览器的cookie中，保存时长为7天。
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = datetime.timedelta(days=7) 

@app.route('/', methods=['GET', 'POST']) # 默认methods=['GET']
def index():
    if 'data' not in session:
        return render_template('index.html')
    
    
    if request.args.get('prompt_idx') and request.args.get('prompt_txt'):
        # 来自/prompt的重定向
        prompt_idx = int(request.args.get('prompt_idx'))
        prompt_txt = request.args.get('prompt_txt')
        if request.args.get('reset'): # 来自/prompt的重来
            messages = []
            session['messages'] = messages
        else: # 来自/prompt的提交
            messages = [{"role":"system", "index":prompt_idx, "content":prompt_txt},]
            session['messages'] = messages
    elif 'messages' in session and len(session['messages']) > 0:
        # 来自/chat的重定向
        messages = session['messages']
        prompt_idx = messages[0]['index']
        prompt_txt = messages[0]['content']
    else:
        # 来自/、/auth等
        prompt_idx = 81
        prompt_txt = prompts[prompt_idx]['prompt']
        messages = []
        session['messages'] = messages
    prompt = {'index':prompt_idx, 'content':prompt_txt}
            
    data = session['data']
    return render_template('index.html', prompts=prompts, prompt=prompt, messages=messages)
    
@app.route('/auth', methods=['POST'])
def auth():
    user = request.form.get('user')
    pwd = request.form.get('pwd')
    
    submit = request.form.get('submit')
    if submit == '注册':
        if not (user and user[0].isalpha() and re.match("^[A-Za-z0-9_]*$", user)) \
                or not pwd:
            return render_template('index.html', auth_msg="输入错误")
        pwd_hash = generate_password_hash(pwd)
        data = {"user": user, "pwd_hash": pwd_hash, "messages": []}
        filepath = "./data/{}.json".format(user) 
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        if not os.path.isfile(filepath):
            return render_template('index.html', auth_msg="注册失败")
        logging.debug(f"signup: user = {user}")
        return render_template('index.html', auth_msg="注册成功")
    elif submit == '登录':
        if not (user and user[0].isalpha() and re.match("^[A-Za-z0-9_]*$", user)) \
                or not pwd:
            return render_template('index.html', auth_msg="输入错误")
        filepath = "./data/{}.json".format(user) 
        if not os.path.isfile(filepath):
            return render_template('index.html', auth_msg="没有注册")
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        if not check_password_hash(data['pwd_hash'], pwd):
            return render_template('index.html', auth_msg="密码错误")
        # 登录成功，存入会话。
        session['data'] = data 
        logging.debug(f"login: user = {user}")
        return redirect(url_for('index'))
    elif submit == '登出':
        # 登出删除会话
        logging.debug(f"logout: user = {user}")
        session.pop('data', None) # 不能用del session['data']，不存在会异常。
        return redirect(url_for('index'))    
    else:
        return redirect(url_for('index'))

@app.route('/prompt', methods=['POST'])
def prompt():
    submit = request.form.get('submit')
    prompt_idx = int(request.form.get('prompt_idx'))
    prompt_txt = request.form.get('prompt_txt')
    if submit == '提交':
        return redirect(url_for('index', prompt_idx=prompt_idx, prompt_txt=prompt_txt))
    elif submit == '重来':
        session.pop('messages', None)
        return redirect(url_for('index', prompt_idx=prompt_idx, \
                                    prompt_txt=prompt_txt, reset=True))
        
@app.route('/chat', methods=['POST'])
def chat():
    chat_ask = request.form.get('chat_ask')
    messages = session['messages']
    messages.append({"role":"user", "content":chat_ask})
    #completion = openai.ChatCompletion.create(model=MODEL, messages=messages) 
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    if completion and 'choices' in completion and len(completion['choices']) > 0 \
        and 'message' in completion['choices'][0] \
        and 'content' in completion['choices'][0]['message']:
        chat_answer = completion.choices[0].message.content
    else:
        chat_answer = ""
    messages.append({"role":"assistant", "content":chat_answer})
    session['messages']=messages
    return redirect(url_for('index'))

 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
    
    
    
    
    
    
    
    
    
    
    
    
    
