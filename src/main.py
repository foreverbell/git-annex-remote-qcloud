#!/usr/bin/env python
# -*- coding: utf-8 -*-

# git-annex external special remote protocol for qcloud (Tencent Cloud).
# References:
# 1. https://git-annex.branchable.com/design/external_special_remote_protocol/
# 2. https://github.com/tochev/git-annex-remote-pcloud
# 3. https://github.com/tencentyun/cos-python-sdk

import functools
import requests, urllib
import os, os.path, sys, traceback
import time
import random
import StringIO, json
import base64, hmac, hashlib
import platform
import ConfigParser

class COSException(Exception):
  def __init__(self, code, message):
    self.code = code
    self.message = message

  def __str__(self):
    return 'qcloud cos exception %d = %s.' % (-self.code, self.message)

class authorizatize(object):
  def __init__(self, app_id, secret_id, secret_key, bucket):
    self.app_id = str(app_id)
    self.secret_id = secret_id
    self.secret_key = secret_key
    self.bucket = bucket

  def app_sign(self, fileid, expired):
    now = int(time.time())
    if not fileid:
      expired += now
    rdm = random.randint(0, 999999999)
    plain_text = 'a=' + self.app_id + '&k=' + self.secret_id + '&e=' + str(expired) + '&t=' + str(now) + '&r=' + str(rdm) + '&f=' + fileid + '&b=' + self.bucket  
    signature = hmac.new(self.secret_key, plain_text, hashlib.sha1).digest() + plain_text
    return base64.b64encode(signature)

  def sign_once(self, fileid):
    return self.app_sign(fileid, 0)

  def sign_more(self, expired):
    return self.app_sign('', expired)

class qcloud_cos(object):
  api_base = 'http://web.file.myqcloud.com/files/v1/'
  expire = 300 # signature expire time = 5 minutes
  timeout = 10 # http connection timeout = 10 seconds

  def __init__(self, app_id, secret_id, secret_key, bucket):
    self.app_id = str(app_id)
    self.secret_id = secret_id
    self.secret_key = secret_key
    self.bucket = bucket
    self.http_session = requests.session()

  def sha1file(self, filename, block=4*1024*1024):
    sha1 = hashlib.sha1()
    with open(filename, 'rb') as f:
      while True:
        data = f.read(block)
        if not data:
          break
        sha1.update(data)
    return sha1.hexdigest()
  
  def mk_headers(self, auth, json=True):
    h = { 'Host': 'web.file.myqcloud.com', 
          'User-Agent': 'Qcloud-Cos-PYTHON/' + ' (' + platform.platform() + ')', # faked user agent lol             
          'Authorization': auth }
    if json:
      h['Content-Type'] = 'application/json'
    return h
	
  def mk_url(self, path):
    return qcloud_cos.api_base + self.app_id + '/' + self.bucket + '/' + path

  def send(self, method, url, **args):
    method = method.upper()
    assert method in ['POST', 'GET'], 'unknown method ' + method
    if method == 'POST':
      r = self.http_session.post(url, **args)
    else:
      r = self.http_session.get(url, **args)
    json = r.json()
    if 'code' in json and json['code'] < 0:
      raise COSException(json['code'], json['message'].encode('utf-8'))
    r.raise_for_status()
    return r

  def __stat(self, auth, server_path):
    url = self.mk_url(server_path)
    signature = auth.sign_more(qcloud_cos.expire)
    return self.send('GET', url, 
        headers=self.mk_headers(signature), 
        params={'op': 'stat'},
        timeout=qcloud_cos.timeout)

  def upload(self, local_path, server_path):
    auth = authorizatize(self.app_id, self.secret_id, self.secret_key, self.bucket)
    if not os.path.exists(local_path):
      raise IOError(local_path + ' file not exists')
    server_path = urllib.quote(server_path)
    url = self.mk_url(server_path)
    signature = auth.sign_more(qcloud_cos.expire)
    self.send('POST', url, 
        headers=self.mk_headers(signature, False), 
        files={'op': 'upload', 'filecontent': open(local_path, 'rb'), 'sha': self.sha1file(local_path)},
        timeout=qcloud_cos.timeout)

  def download(self, local_path, server_path):
    auth = authorizatize(self.app_id, self.secret_id, self.secret_key, self.bucket)
    server_path = urllib.quote(server_path)
    response = self.__stat(auth, server_path)
    access_url = response.json()['data']['access_url'] + '?sign=' + auth.sign_more(qcloud_cos.expire)
    urllib.urlretrieve(access_url, local_path)
    
  def present(self, server_path):
    auth = authorizatize(self.app_id, self.secret_id, self.secret_key, self.bucket)
    server_path = urllib.quote(server_path)
    is_present = True
    try:
      response = self.__stat(auth, server_path)
    except COSException as e:
      if e.code != -166: # ERROR_CMD_COS_INDEX_ERROR = -166
        raise
      else:
        is_present = False
    return is_present
  
  def delete(self, server_path):
    auth = authorizatize(self.app_id, self.secret_id, self.secret_key, self.bucket)
    server_path = urllib.quote(server_path)
    url = self.mk_url(server_path)
    signature = auth.sign_once('/' + self.app_id + '/' + self.bucket + '/' + server_path)
    self.send('POST', url, 
        headers=self.mk_headers(signature), 
        data=json.dumps({'op': 'delete'}),
        timeout=qcloud_cos.timeout)

def report(indices=[], eheader=None):
  def decorator(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
      try:
        f(*args, **kwargs)
      except Exception as e:
        for line in traceback.format_exc().splitlines():
          args[0].debug(line)
        args[0].send(eheader or (f.__name__.upper() + '-FAILURE'), *([args[i] for i in indices] + ['. '.join(str(e).splitlines())]))
        if isinstance(e, (COSException, requests.RequestException, IOError)):
          return
        else:
          raise
      else:
        if not eheader:
          args[0].send(f.__name__.upper() + '-SUCCESS', *[args[i] for i in indices])
    return wrapper
  return decorator

class qcloud_git_annex_remote(object):
  supported_cmds = ['initremote', 'prepare', 'transfer', 'checkpresent', 'remove', 'getcost' ]

  def send(self, *args):
    sys.stdout.write(' '.join(map(str, args)) + '\n')
    sys.stdout.flush()

  def debug(self, *args):
    self.send('DEBUG', *args)

  def dirhash(self, key):
    self.send('DIRHASH', key)
    response = sys.stdin.readline().strip().split()
    assert len(response) == 2 and response[0] == 'VALUE', 'unknown response to DIRHASH'
    return response[1]
  
  def from_key(self, key):
    return self.dirhash(key) + key

  def init_qcloud_cos(self):
    credentials = os.environ.get('QCLOUD_CREDENTIALS')
    if not credentials:
      raise IOError('credentials environment variable QCLOUD_CREDENTIALS not found')
    credentials = os.path.expanduser(credentials)
    config = ConfigParser.RawConfigParser()
    config.readfp(StringIO.StringIO('[default]\n' + open(credentials, 'r').read()))
    app_id = config.get('default', 'app_id')
    secret_id = config.get('default', 'secret_id')
    secret_key = config.get('default', 'secret_key')
    bucket = config.get('default', 'bucket')
    self.qcloud_cos = qcloud_cos(app_id, secret_id, secret_key, bucket)

  @report()
  def initremote(self):
    # TODO: do some stuffs like create bucket, but this operation seems not to be supported by qcloud.
    self.init_qcloud_cos()

  @report()
  def prepare(self):
    self.init_qcloud_cos()
  
  @report([1, 2])
  def transfer(self, direction, key, local_path):
    server_path = self.from_key(key)
    assert direction in ['STORE', 'RETRIEVE'], 'unknown direction of TRANSFER'
    if direction == 'STORE':
      self.qcloud_cos.upload(local_path, server_path)
    else: 
      self.qcloud_cos.download(local_path, server_path)
  
  @report([1], 'CHECKPRESENT-UNKNOWN')
  def checkpresent(self, key):
    server_path = self.from_key(key)
    r = self.qcloud_cos.present(server_path)
    self.send('CHECKPRESENT-' + ('SUCCESS' if r else 'FAILURE'), key)
  
  @report([1])
  def remove(self, key):
    server_path = self.from_key(key)
    self.qcloud_cos.delete(server_path)

  def getcost(self): 
    self.send('COST', 200)
    
  def main(self):
    self.send('VERSION 1')
    while True:
      line = sys.stdin.readline()
      if not line:
        break
      splices = line.split()
      cmd = splices[0].lower()
      args = splices[1:]
      if cmd not in self.supported_cmds:
        self.send('UNSUPPORTED-REQUEST') 
        continue
      getattr(self, cmd)(*args)

if __name__ == '__main__':
  qcloud_git_annex_remote().main()
