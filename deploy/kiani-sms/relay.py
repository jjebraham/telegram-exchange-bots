"""Fixed text-only Ghasedak relay using the verified 30005088 sender."""
import hashlib
import json
import os
import re
import signal
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://gateway.ghasedak.me/rest/api/v1/WebService/'
MAX_BODY = 65536
SENDER = '30005088'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def field(value, name):
    return value.get(name, value.get(name[0].upper()+name[1:])) if isinstance(value, dict) else None


def mobile(value):
    digits = re.sub(r'[^0-9]', '', str(value))
    if digits.startswith('0098'): digits = '0' + digits[4:]
    elif digits.startswith('98'): digits = '0' + digits[2:]
    return digits


def run():
    if os.environ.get('SSH_ORIGINAL_COMMAND') != 'ghasedak-v1':
        return {'ok':False,'error':'unsupported_command'}
    signal.alarm(20)
    raw = sys.stdin.buffer.read(16385)
    if len(raw)>16384: return {'ok':False,'error':'request_too_large'}
    command = json.loads(raw)
    action = command.get('action')
    key = command.get('api_key')
    if action not in {'account_info','template_info','send_otp','message_status'}:
        return {'ok':False,'error':'unsupported_action'}
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{16,2048}',key):
        return {'ok':False,'error':'invalid_credentials_format'}
    if action in {'template_info','send_otp'}:
        template = command.get('template')
        if not isinstance(template,str) or not 1<=len(template)<=100 or any(ord(c)<32 for c in template):
            return {'ok':False,'error':'invalid_template'}
    data = None
    if action=='account_info':
        endpoint = 'GetAccountInformation'
    elif action=='message_status':
        message_id=command.get('message_id')
        if not isinstance(message_id,str) or not re.fullmatch(r'[1-9][0-9]{0,63}',message_id):
            return {'ok':False,'error':'invalid_message_id'}
        endpoint='CheckSmsStatus?' + urllib.parse.urlencode({'Type':1,'Ids':message_id})
    elif action=='template_info':
        endpoint = 'GetOtpTemplateParameters?' + urllib.parse.urlencode({'TemplateName':template})
    else:
        phone,otp,reference,parameter = (command.get(k) for k in ('phone','otp','reference','parameter'))
        if (not isinstance(phone,str) or not re.fullmatch(r'09[0-9]{9}',phone)
                or not isinstance(otp,str) or not re.fullmatch(r'[0-9]{6}',otp)
                or not isinstance(reference,str) or not re.fullmatch(r'[a-f0-9]{32}',reference)
                or not isinstance(parameter,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,49}',parameter)):
            return {'ok':False,'error':'invalid_otp_request'}
        # Retrieve the approved template text, then use the verified sender.
        # SendSingleSMS is text-only and accepts an explicit line number.
        signal.alarm(28)
        template_request=urllib.request.Request(BASE+'GetOtpTemplateParameters?'+urllib.parse.urlencode({'TemplateName':template}),
            headers={'ApiKey':key,'Accept':'application/json','Cache-Control':'no-cache'})
        template_opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        try:
            with template_opener.open(template_request,timeout=8) as template_response:
                template_raw=template_response.read(MAX_BODY+1)
        except urllib.error.HTTPError as error:
            return {'ok':False,'error':'template_metadata_http_error','http_status':error.code,'action':action}
        if len(template_raw)>MAX_BODY:return {'ok':False,'error':'template_metadata_too_large','action':action}
        template_result=json.loads(template_raw)
        template_payload=field(template_result,'data')
        template_text=field(template_payload,'message')
        placeholder='%'+parameter+'%'
        if (field(template_result,'isSuccess') is not True or field(template_payload,'params')!=[parameter]
                or not isinstance(template_text,str) or not 1<=len(template_text)<=1000
                or placeholder not in template_text
                or re.search(r'%[A-Za-z][A-Za-z0-9_]*%',template_text.replace(placeholder,''))):
            return {'ok':False,'error':'unsupported_saved_template','action':action}
        template_sha256=hashlib.sha256(template_text.encode()).hexdigest()
        rendered_text=template_text.replace(placeholder,otp)
        if len(rendered_text)>1000:return {'ok':False,'error':'rendered_template_too_large','action':action}
        endpoint='SendSingleSMS'
        body={'lineNumber':SENDER,'receptor':phone,'clientReferenceId':reference,
              'message':rendered_text,'udh':False}
        data=json.dumps(body).encode()
    request = urllib.request.Request(BASE+endpoint,data=data,
        headers={'ApiKey':key,'Accept':'application/json','Content-Type':'application/json','Cache-Control':'no-cache'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def provider_message(value):
        message=str(field(value,'message') or '')
        for secret in (key,command.get('phone'),command.get('otp')):
            if secret:message=message.replace(secret,'[redacted]')
        return re.sub(r'\b\d{6,}\b','[redacted]',message)[:200]
    try:
        with opener.open(request,timeout=12) as response:
            status = response.status
            body = response.read(MAX_BODY+1)
    except urllib.error.HTTPError as error:
        try:failure=json.loads(error.read(MAX_BODY+1))
        except Exception:failure={}
        return {'ok':False,'error':'provider_http_error','http_status':error.code,'action':action,
                'provider_code':str(field(failure,'statusCode'))[:16],
                'provider_message':provider_message(failure)}
    if len(body)>MAX_BODY: return {'ok':False,'error':'provider_response_too_large','action':action}
    parsed=json.loads(body)
    code=field(parsed,'statusCode')
    if field(parsed,'isSuccess') is not True:
        return {'ok':False,'error':'provider_rejected','http_status':status,
                'provider_code':str(code)[:16] if isinstance(code,(str,int)) else None,'action':action,
                'provider_message':provider_message(parsed)}
    result={'ok':True,'protocol':1,'provider':'ghasedak.me','action':action,
            'http_status':status,'provider_code':str(code)[:16] if isinstance(code,(str,int)) else None}
    payload=field(parsed,'data')
    if action=='account_info':
        credit=field(payload,'credit')
        result['credit_positive']=isinstance(credit,(int,float)) and not isinstance(credit,bool) and credit>0
        result['expire_date']=str(field(payload,'expireDate') or '')[:64]
        result['plan']=str(field(payload,'plan') or '')[:80]
    elif action=='template_info':
        parameters=field(payload,'params')
        if not isinstance(parameters,list) or not all(isinstance(p,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,49}',p) for p in parameters):
            return {'ok':False,'error':'unsupported_template_parameters','action':action}
        result['parameters']=parameters
    elif action=='message_status':
        if (not isinstance(payload,list) or len(payload)!=1
                or str(field(payload[0],'messageId'))!=message_id):
            return {'ok':False,'error':'invalid_message_status','action':action}
        result['statuses']=[{name:field(item,name) for name in ('messageId','status','statusCode','deliveryStatus','statusDate')
                             if isinstance(field(item,name),(str,int,float))} for item in payload]
        for item,summary in zip(payload,result['statuses']):
            reference=field(item,'clientReferenceId')
            if isinstance(reference,str) and re.fullmatch(r'[a-f0-9]{32}',reference):
                summary['client_reference']=reference
            summary['recipient_suffix']=mobile(field(item,'receptor'))[-4:]
            summary['sender_line']=str(field(item,'lineNumber') or field(item,'sender') or '')[:32]
            summary['send_date']=str(field(item,'sendDate') or '')[:64]
            for name in ('errorCode','statusReason','statusDescription','deliveryDescription','errorMessage'):
                value=field(item,name)
                if isinstance(value,(str,int)):
                    summary[name]=re.sub(r'\b\d{6,}\b','[redacted]',str(value))[:200]
    else:
        message_id=str(field(payload,'messageId') or '')
        sender=str(field(payload,'lineNumber') or '')
        if (mobile(field(payload,'receptor'))!=phone or sender not in (SENDER,'98'+SENDER,'+98'+SENDER)
                or not message_id.isdigit() or int(message_id)<=0 or len(message_id)>64):
            return {'ok':False,'error':'invalid_message_acknowledgement','action':action}
        result.update(message_id=message_id,method='SendSingleSMS',sender_line=SENDER,
                      source_template=template,template_content_sha256=template_sha256)
    return result


try:
    output=run()
except Exception:
    output={'ok':False,'error':'relay_unavailable'}
print(json.dumps(output,separators=(',',':')))
