#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# fproc: file processing
import requests
import chardet
from bs4 import BeautifulSoup

def find_encoding(response):
    encoding = None
    # 从headers中获取charset 
    if response.headers:
        # encoding = response.encoding
        encoding = requests.utils.get_encoding_from_headers(response.headers)
        #当headers中没有Content-Type时默认为"ISO-8859-1"
        if encoding == 'ISO-8859-1':
            encoding = None
    # 从content中获取charset
    if not encoding:
        # encoding = response.apparent_encoding
        # requests的bug：不能对bytes进行正则匹配，只能对string进行正则匹配。
        #encoding = requests.utils.get_encodings_from_content(response.content)
        encoding = requests.utils.get_encodings_from_content(response.text)
        encoding = encoding and encoding[0] or None
    # 利用chardet模块猜字符编码(不一定对)
    if not encoding:
        encoding = chardet.detect(response.content)['encoding']
    # gb18030完全兼容gb2312，把gb2312改为gb18030正确率更高。
    if encoding and encoding.lower() == 'gb2312':
        encoding = 'gb18030'
    return encoding or 'latin_1'

def crawl_webpage(url):
    # 下载网页
    response = requests.get(url=url)
    if response.status_code != 200:
        print(f"requests错误: status_code={response.status_code}")
        return (False, "抓取网页失败")
    # 从网页中提取title和paragraphs
    #charset = requests.utils.get_encodings_from_content(response.text)[0]
    charset = find_encoding(response)
    try:
        # soup = BeautifulSoup( \
        # response.text.encode(response.encoding).decode(charset), \
        # 'html.parser', from_encoding=charset)
        soup = BeautifulSoup(response.content.decode(charset), \
                             'html.parser', from_encoding=charset)
    except UnicodeDecodeError as err:
        print(f"requests错误: error={err}")
        return (False, "网页解码错误")
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
    return (True, (title, paragraphs))




