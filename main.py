import os, re, datetime, json, logging
from flask import Flask, request, redirect, url_for, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash
import pymongo
import openai

# 日志基本配置
logging.basicConfig(filename='./logging.txt', 
                    filemode='a',       # 'w'为覆盖，'a'为追加
                    format="%(asctime)s [%(levelname)s] %(message)s ",
                    level=logging.DEBUG # 只打印level及level以上的消息
                    )

# 获取全局变量
if os.getenv("DEPLOY_ON_RAILWAY"):
    # 在railway部署：从系统中获取环境变量
    PORT = os.getenv("PORT")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    openai.api_key = OPENAI_API_KEY
    OPENAI_MODEL = os.getenv("OPENAI_MODEL")
    MONGO_URL = os.getenv("MONGO_URL")
    logging.debug(f'PORT = {PORT}')
    logging.debug(f'OPENAI_API_KEY ={OPENAI_API_KEY}')
    logging.debug(f'OPENAI_MODEL ={OPENAI_MODEL}')
    logging.debug(f'MONGO_URL ={MONGO_URL}')
else:
    # 在本地部署：读取配置文件中的变量
    with open("./config.json", encoding='utf-8') as f:
        config = json.load(f)  # 读取配置文件
    PORT = config["PORT"]
    OPENAI_API_KEY = config["OPENAI_API_KEY"]
    openai.api_key = OPENAI_API_KEY
    OPENAI_MODEL = config["OPENAI_MODEL"]
    HTTP_PROXY = config['HTTP_PROXY']
    os.environ['HTTP_PROXY'] = HTTP_PROXY
    HTTPS_PROXY = config['HTTPS_PROXY']
    os.environ['HTTPS_PROXY'] = HTTPS_PROXY
    MONGO_URL = config['MONGO_URL']
    logging.debug(f'PORT = {PORT}')
    logging.debug(f'OPENAI_API_KEY ={OPENAI_API_KEY}')
    logging.debug(f'OPENAI_MODEL ={OPENAI_MODEL}')
    logging.debug(f'HTTP_PROXY ={HTTP_PROXY}')
    logging.debug(f'HTTPS_PROXY ={HTTPS_PROXY}')
    logging.debug(f'MONGO_URL ={MONGO_URL}')


# 获取提示列表 
with open("./prompts.json", encoding='utf-8') as f:
    prompts = json.load(f)

# 创建Flask应用: 密钥用来加密session到浏览器的cookie中，保存时长为2天。
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = datetime.timedelta(days=2) 

# 获得MongoDB客户端
mongo_client = pymongo.MongoClient(MONGO_URL)
# 获取MongoDB的数据库和集合
mongo_db = mongo_client['DQA']
mongo_col = mongo_db['user_info']

@app.route('/', methods=['GET', 'POST']) # 默认methods=['GET']
def index():
    if 'name' not in session:
        # 1)验证阶段：没有登录
        return render_template('index.html')
    elif ("prompt_idx" not in session) \
            or ("prompt" not in session) \
            or ('messages' not in session):
        # 2)提示阶段：没有提示
        session['state'] = 'prompt'
        prompt_idx = 81
        prompt = prompts[prompt_idx]['prompt']
        session['prompt_idx'] = prompt_idx
        session['prompt'] = prompt
    else:
        # 3)问答阶段：进入问答
        session['state'] = 'chat'
                
    return render_template('index.html', prompts=prompts)
    
@app.route('/auth', methods=['POST'])
def auth():
    name = request.form.get('name')
    pwd = request.form.get('pwd')
    
    submit = request.form.get('submit')
    if submit == '注册':
        # 验证输入
        if not (name and name[0].isalpha() and re.match("^[A-Za-z0-9_]*$", name)) \
                or not pwd:
            return render_template('index.html', auth_msg="输入错误")
        if list(mongo_col.find({"name":name})) != []:
            return render_template('index.html', auth_msg="账号存在")
        # 用户信息
        pwd_hash = generate_password_hash(pwd)
        user_dict = {"name": name, "pwd_hash": pwd_hash}
        # 新增记录
        res = mongo_col.insert_one(user_dict)
        if list(mongo_col.find({"name":name})) == []:
            return render_template('index.html', auth_msg="注册失败")
        logging.debug(f"注册: name={name}, pwd_hash={pwd_hash}")
        return render_template('index.html', auth_msg="注册成功")
    elif submit == '登录':
        # 验证输入
        if not (name and name[0].isalpha() and re.match("^[A-Za-z0-9_]*$", name)) \
                or not pwd:
            return render_template('index.html', auth_msg="输入错误")
        if list(mongo_col.find({"name":name})) == []:
            return render_template('index.html', auth_msg="没有注册")
        # 查询记录
        user_dict = mongo_col.find({"name":name})[0]
        if not check_password_hash(user_dict['pwd_hash'], pwd):
            return render_template('index.html', auth_msg="密码错误")
        # 写入验证会话
        session['name'] = user_dict['name']
        if ('prompt_idx' in user_dict) \
                and ('prompt' in user_dict) \
                and ('messages' in user_dict): 
            session['prompt_idx'] = user_dict['prompt_idx']
            session['prompt'] = user_dict['prompt']
            session['messages'] = user_dict['messages']
        logging.debug(f"登录: name={name}, session={session}")
        return redirect(url_for('index'))
    elif submit == '登出':
        # 清空所有会话：验证会话+问答会话
        query = {"name": session["name"]}
        if ('prompt_idx' in session) and ('prompt' in session) and ('messages' in session):
            update = {"$set": {"prompt_idx":session["prompt_idx"], \
                               "prompt":session["prompt"], \
                               "messages":session["messages"]}}
            mongo_col.update_one(query, update)    
        session.pop('name', None) # 不能用del session['name']，不存在会异常。
        session.pop('prompt_idx', None)
        session.pop('prompt', None)
        session.pop('messages', None)
        logging.debug(f"登出: name={name}, session={session}")
        return redirect(url_for('index'))    
    else:
        # /auth页面跳转回/页面
        return redirect(url_for('index'))

@app.route('/prompt', methods=['POST'])
def prompt():
    submit = request.form.get('submit')
    prompt_idx = int(request.form.get('prompt_idx'))
    prompt_txt = request.form.get('prompt_txt')
    if submit == '提交':
        # 写入问答会话
        session['prompt_idx'] = prompt_idx
        session['prompt'] = prompt_txt
        messages = [{"role": "system", "content": prompt_txt}]
        session['messages'] = messages
        mongo_col.update_one({"name": session["name"]}, \
                {"$set": {"prompt_idx":session["prompt_idx"], \
                          "prompt":session["prompt"], \
                          "messages":session["messages"]}}) 
        logging.debug("提交：prompt_idx={}, prompt={}, messages={}".format( \
            session['prompt_idx'], session['prompt'], session['messages']))
        return redirect(url_for('index'))
    elif submit == '重来':
        # 清空问答会话
        logging.debug("重来: prompt_idx={}, prompt={}, len(messages)={}".format( \
            session.get('prompt_idx'), session.get('prompt'), len(session.get('messages'))))
        session.pop('prompt_idx', None)
        session.pop('prompt', None)
        session.pop('messages', None)
        return redirect(url_for('index'))
    else:
        # /auth页面跳转回/页面
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
        chat_msg = ""
        try:
            #Make your OpenAI API request here
            completion = openai.ChatCompletion.create(
                                        model=OPENAI_MODEL, # OPENAI_MODEL == "gpt-3.5-turbo" 
                                        messages=messages,
                                        temperature=0.6,
                                        max_tokens=2048) 
            #response = openai.Completion.create(prompt="Hello world",
            #                              model="text-davinci-003")
        except openai.error.APIError as e:
            #Handle API error here, e.g. retry or log
            chat_msg = f"OpenAI API returned an API Error: {e}"
            logging.error(chat_msg)
            pass    # 忽略异常，继续执行。
        except openai.error.APIConnectionError as e:
            #Handle connection error here
            chat_msg = f"Failed to connect to OpenAI API: {e}"
            logging.error(chat_msg)
            pass
        except openai.error.RateLimitError as e:
            #Handle rate limit error (we recommend using exponential backoff)
            chat_msg = f"OpenAI API request exceeded rate limit: {e}"
            logging.error(chat_msg)
            pass
        if chat_msg:
            return render_template('index.html', prompts=prompts, chat_msg=chat_msg)
        # 提取回答
        if completion and 'choices' in completion and len(completion['choices']) > 0 \
            and 'message' in completion['choices'][0] \
            and 'content' in completion['choices'][0]['message']:
            chat_answer = completion.choices[0].message.content
        else:
            # chat_completion_format错误
            chat_msg = f"chat_completion_format错误： completion={completion}"
            logging.error(chat_msg)
            return render_template('index.html', prompts=prompts, chat_msg=chat_msg)
        # 成功问答
        messages.append({"role":"assistant", "content":chat_answer})
        session['messages']=messages
        mongo_col.update_one({"name": session["name"]}, \
                {"$set": {"messages":session["messages"]}})
        logging.debug("回答: prompt_idx={}, prompt={}, messages={}".format( \
                        session['prompt_idx'], session['prompt'], session['messages']))
        return redirect(url_for('index'))
    elif submit == '删除':
        # message_idx为某轮问答的发问对应的messages索引
        message_idx = request.form.get('message_idx')
        print("type(message_idx)={}, message_idx={}".format(type(message_idx), message_idx))
        message_idx = int(message_idx)
        if ('messages' not in session) or (message_idx not in [1, 3, 5, 7, 9]):
            return redirect(url_for('index'))
        messages = session['messages']
        old_len = len(messages)
        # 删除message_idx和message_idx之后的所有问答
        messages = messages[:message_idx]
        session['messages'] = messages
        mongo_col.update_one({"name": session["name"]}, \
                {"$set": {"messages":session["messages"]}})
        logging.debug( \
            "删除: prompt_idx={}, prompt={}, len(old_messages)={}, len(new_messages)={}".format( \
            session['prompt_idx'], session['prompt'], old_len, len(session['messages'])))
        return redirect(url_for('index'))
    else:
        return redirect(url_for('index'))
 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
    
    
    
    
    
    
    
    
    
    
    
    
    
