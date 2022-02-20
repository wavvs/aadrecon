import click
import http.client
import ssl
import xmltodict
import requests
import json
import dns.resolver as dnsresolver
import dns.exception as dnsexception
import dns.rdatatype as dnsrdatatype
import concurrent.futures
import signal
import os

from inspect import getsourcefile
from os.path import abspath, dirname, join, exists

SOAP = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:exm="http://schemas.microsoft.com/exchange/services/2006/messages" xmlns:ext="http://schemas.microsoft.com/exchange/services/2006/types" xmlns:a="http://www.w3.org/2005/08/addressing" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
	<soap:Header>
		<a:Action soap:mustUnderstand="1">http://schemas.microsoft.com/exchange/2010/Autodiscover/Autodiscover/GetFederationInformation</a:Action>
		<a:To soap:mustUnderstand="1">https://autodiscover-s.outlook.com/autodiscover/autodiscover.svc</a:To>
		<a:ReplyTo>
			<a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
		</a:ReplyTo>
	</soap:Header>
	<soap:Body>
		<GetFederationInformationRequestMessage xmlns="http://schemas.microsoft.com/exchange/2010/Autodiscover">
			<Request>
				<Domain>{domain}</Domain>
			</Request>
		</GetFederationInformationRequestMessage>
	</soap:Body>
</soap:Envelope>
"""

def get_credential_type(username, flowtoken=''):
    body = {
        "username": username,
        "isOtherIdpSupported": "true",
        "checkPhones": "true",
        "isRemoteNGCSupported": "false",
        "isCookieBannerShown": "false",
        "isFidoSupported": "false",
        "originalRequest": "",
        "flowToken": flowtoken
    }
    r = requests.post('https://login.microsoftonline.com/common/GetCredentialType', json=body)
    if r.status_code == 200:
        return r.json()
    else:
        return {'error': '{};{}'.format(r.status_code, r.json())}

def get_user_realm(username):
    r = requests.get('https://login.microsoftonline.com/GetUserRealm.srf?login='+username)
    if r.status_code == 200:
        return r.json()
    else:
        return {'error': '{};{}'.format(r.status_code, r.json())}

def has_desktop_sso(domain):
    ct = get_credential_type('zz@'+domain)
    if 'error' in ct:
        ct['desktop_sso'] = None
        return ct
    val = ct.get('EstsProperties', {}).get('DesktopSsoEnabled', False)
    return {'desktop_sso': val}

def dns_wrap(func, resolver, domain):
    try:
        return func(resolver, domain)
    except (dnsresolver.NoNameservers, dnsresolver.NXDOMAIN, dnsresolver.LifetimeTimeout):
        return False
    except dnsexception.DNSException as e:
        return {'error': str(e)}

def has_dns(resolver, domain):
    resolver.resolve(domain, raise_on_no_answer=False)
    return True

def has_cloud_mx(resolver, domain):
    answers = resolver.resolve(domain, dnsrdatatype.MX, raise_on_no_answer=False)
    for i in answers:
        if str(i.exchange).endswith('mail.protection.outlook.com.'):
            return True
    return False

def has_cloud_spf(resolver, domain):
    answers = resolver.resolve(domain, dnsrdatatype.TXT, raise_on_no_answer=False)
    for i in answers:
        if 'include:spf.protection.outlook.com' in i.to_text():
            return True
    return False

def has_dmarc(resolver, domain):
    answers = resolver.resolve('_dmarc.'+domain, dnsrdatatype.TXT, raise_on_no_answer=False)
    for i in answers:
        if 'v=DMARC1' in i.to_text():
            return True
    return False

def get_tenant_id(domain):
    url = 'https://login.microsoftonline.com/{}/.well-known/openid-configuration'.format(domain)
    r = requests.get(url)
    oidc = r.json()
    if r.status_code == 200:
        return {"tenant_id" : oidc['authorization_endpoint'].split('/')[3]}
    elif r.status_code == 400:
        if oidc['error'] == 'invalid_tenant':
            return {'tenant_id' : ''}
        else:
            return {'tenant_id' : None, 'error': oidc['error_description']}
    else:
        return {'tenant_id' : None, 'error': '{};{}'.format(r.status_code, oidc)}

def get_tenant_domains(domain):
    body = SOAP.format(domain=domain).encode('ascii')
    connection = http.client.HTTPSConnection("autodiscover-s.outlook.com", context=ssl._create_unverified_context())
    connection.putrequest('POST', "/autodiscover/autodiscover.svc", skip_accept_encoding=True)
    connection.putheader('Content-Type', 'text/xml; charset=utf-8')
    connection.putheader('SOAPAction', '"http://schemas.microsoft.com/exchange/2010/Autodiscover/Autodiscover/GetFederationInformation"')
    connection.putheader('User-Agent', 'AutodiscoverClient')
    connection.putheader('Content-Length', str(len(body)))
    connection.endheaders(message_body=body)
    response = connection.getresponse()
    data = response.read()
    if response.status == 200:
        root = xmltodict.parse(data)
        domains = root['s:Envelope']['s:Body']['GetFederationInformationResponseMessage']['Response']['Domains']['Domain']
        return {'domains': domains}

    return {'domains': None, 'error': '{};{}'.format(response.status, data.decode('ascii'))}

def worker(domain, resolver):
    domain_d = {domain: {}}
    realm = get_user_realm('zz@'+domain)
    if 'error' in realm:
        domain_d[domain] = realm
    else:
        domain_d[domain]['type'] = realm['NameSpaceType'].lower()
        auth_url = realm.get('AuthURL', None)
        if auth_url is not None:
            domain_d[domain]['sts'] = auth_url.split('/')[2]

    domain_d[domain]['dns'] = dns_wrap(has_dns, resolver, domain)
    domain_d[domain]['mx'] = dns_wrap(has_cloud_mx, resolver, domain)
    domain_d[domain]['spf'] = dns_wrap(has_cloud_spf, resolver, domain)
    domain_d[domain]['dmarc'] = dns_wrap(has_dmarc, resolver, domain)
    return domain_d

@click.command()
@click.option('--domains', '-d', type=str, help='Domains to search (domain1,...,domainN)')
@click.option('--fdomains', '-f', type=click.Path(exists=True), help='File with new-line delimited domains')
@click.option('--threads', '-t', type=int, default=10)
def cli(domains, fdomains, threads):
    '''Azure AD reconnaissance as outsider'''
    script_dir = dirname(abspath(getsourcefile(lambda:0)))
    resolvers_file = join(script_dir, 'resolvers-actions.txt')
    if not exists(resolvers_file):
        r = requests.get('https://raw.githubusercontent.com/wavvs/validns/main/data/resolvers-actions.txt')
        with open(join(script_dir, 'resolvers-actions.txt'), 'wb') as f:
            f.write(r.content)
    
    with open(resolvers_file, 'r') as f:
        resolvers = [i.strip() for i in f.readlines()]
    resolver = dnsresolver.Resolver(configure=False)
    resolver.nameservers = resolvers
    resolver.timeout = 5
    resolver.lifetime = 30

    if fdomains is not None:
        with open(fdomains, 'r') as f:
            domains = [i.strip() for i in f.readlines() if len(i) > 0]
    else:
        domains = [i.strip() for i in domains.split(',') if len(i) > 0]

    out = {}
    seen_domains = {}
    for domain in domains:
        if domain in seen_domains:
            continue

        tid = get_tenant_id(domain)
        tenant_id = tid['tenant_id']    
        if tenant_id is None:
            out[domain] = {'domain': domain, 'error': tid['error']}
            continue

        if tenant_id == "":
            continue
        
        out[domain] = {'tenant_id': tenant_id}
        
        sso = has_desktop_sso(domain)
        if sso['desktop_sso'] is None:
            out[domain].update({'domain': domain, 'error': sso['error']})
            continue
        
        out[domain].update(sso)
        
        realm = get_user_realm('zz@'+domain)
        if realm is None:
            out[domain].update({'domain': domain, 'error': realm['error']})
        out[domain]['tenant_brand'] = realm['FederationBrandName']

        ds = get_tenant_domains(domain)
        dms = ds['domains']
        if dms is None:
            out[domain].update({'error': ds['error']})
            continue

        if 'domains' not in out[domain]:
            out[domain]['domains'] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            tasks = [executor.submit(worker, domain, resolver) for domain in dms]
            for task in concurrent.futures.as_completed(tasks):
                domain_d = task.result()
                out[domain]['domains'].update(domain_d)

        seen_domains[domain] = True
        seen_domains.update(dict.fromkeys(dms, True))
       
    for k in out:
        print(json.dumps(out[k]))


def signal_handler(signal, frame):
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
    cli()
