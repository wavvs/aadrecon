# AADRecon
Python implementation of the [Invoke-AADIntReconAsOutsider](https://o365blog.com/aadinternals/#invoke-aadintreconasoutsider) function from the [AADInternals](https://github.com/Gerenios/AADInternals) suite.

## Usage

```bash
$ python3 aadrecon.py --help
Usage: aadrecon.py [OPTIONS]

  Azure AD reconnaissance as outsider

Options:
  -d, --domains TEXT     Domains to search (domain1,...,domainN)
  -f, --fdomains PATH    File with new-line delimited domains
  -t, --threads INTEGER
  --help                 Show this message and exit.
```
Example:
```bash
$ python3 aadrecon.py -d python.org,github.com | jq
```
Output:
```json
{
  "tenant_id": "13faecd2-f4dc-42b6-8a54-d714cbaac738",
  "desktop_sso": false,
  "tenant_brand": "python.org",
  "domains": {
    "python.org": {
      "type": "managed",
      "dns": true,
      "mx": false,
      "spf": false,
      "dmarc": true
    },
    "pythonorg.onmicrosoft.com": {
      "type": "managed",
      "dns": false,
      "mx": false,
      "spf": false,
      "dmarc": false
    }
  }
}
{
  "tenant_id": "72f988bf-86f1-41af-91ab-2d7cd011db47",
  "desktop_sso": false,
  "tenant_brand": "Microsoft",
  "domains": {
    "microsoft.com": {
      "type": "federated",
      "sts": "msft.sts.microsoft.com",
      "dns": true,
      "mx": true,
      "spf": false,
      "dmarc": true
    },
    "HaloWaypoint.com": {
      "type": "managed",
      "dns": true,
      "mx": true,
      "spf": false,
      "dmarc": true
    },
    "bing.com": {
      "type": "managed",
      "dns": true,
      "mx": true,
      "spf": true,
      "dmarc": true
    },
    /*TRUNCATED*/
```

## Credits
* https://o365blog.com/aadinternals/