# ATS resolution report

- `config/companies.yaml` (fetched every run): 688
- `config/unresolved_companies.yaml` (not fetchable): 2016

## Fetchable, by vendor

- personio: 324
- ashby: 83
- greenhouse: 68
- workday: 50
- join: 49
- softgarden: 32
- smartrecruiters: 28
- recruitee: 19
- lever: 16
- workable: 10
- bamboohr: 5
- onlyfy: 4

## Not fetchable, by reason

- careers page has no supported ATS: 888
- no careers page found on the site: 590
- domain doesn't resolve (DNS) - site gone?: 87
- homepage TLS/SSL error: 85
- homepage blocks automated requests (HTTP 403): 68
- homepage unreachable (ConnectError): 37
- homepage timed out: 36
- homepage returns HTTP 404: 34
- rexx: no adapter yet: 20
- careers page uses successfactors (no adapter yet): 16
- teamtailor: no adapter yet: 15
- personio endpoint is gone (404): 14
- careers page uses notion (no adapter yet): 8
- careers page has JSON-LD JobPosting data (generic-adapter candidate): 8
- careers page uses hrworks (no adapter yet): 8
- homepage returns HTTP 500: 7
- careers page uses cornerstone (no adapter yet): 7
- homepage returns HTTP 503: 6
- homepage blocks automated requests (HTTP 429): 5
- careers page uses phenom (no adapter yet): 5
- homepage returns HTTP 522: 5
- careers page uses avature (no adapter yet): 5
- careers page uses factorial (no adapter yet): 5
- homepage returns HTTP 402: 4
- careers page uses zoho (no adapter yet): 4
- recruitee endpoint is gone (404): 3
- careers page uses talention (no adapter yet): 3
- careers page uses breezy (no adapter yet): 3
- careers page uses oracle (no adapter yet): 3
- careers page uses dvinci (no adapter yet): 3
- careers page uses bite (no adapter yet): 3
- careers page uses umantis (no adapter yet): 2
- smartrecruiters endpoint is gone (404): 2
- homepage unreachable (RemoteProtocolError): 2
- homepage returns HTTP 409: 2
- detection crashed - see the run log: 2
- homepage blocks automated requests (HTTP 401): 2
- softgarden endpoint is gone (404): 2
- homepage returns HTTP 423: 1
- homepage returns HTTP 502: 1
- removed by hand 2026-10-23 - domain now redirects to a gambling shop (ecommercegenius.shop): 1
- homepage returns HTTP 525: 1
- careers page uses hibob (no adapter yet): 1
- lever endpoint is gone (404): 1
- careers page uses phenom, successfactors (no adapter yet): 1
- homepage returns HTTP 410: 1
- homepage unreachable (TooManyRedirects): 1
- duplicate of CARSYNC (VISPIRON) - motum's site redirects to carsync.de; jobs fetched via JOIN vispiron-gmbh (checked by hand 2026-10-23): 1
- greenhouse endpoint is gone (404): 1
- careers page uses notion, pinpoint (no adapter yet): 1
- careers page uses teamtailor (no adapter yet): 1
- homepage returns HTTP 406: 1
- homepage returns HTTP 405: 1
- removed by hand 2026-10-23 (not a fit): 1
- workday endpointtenant': 'nxp', 'wd_host': 'wd3', 'site': 'careers'}' is gone (404): 1

## Moved to companies.yaml this run

- Dell Technologies Germany — personio:dell — https://www.dell.com/de-de
- Neohelden — personio:msg-industry-advisors-ag — https://neohelden.com/
- jember — personio:jember — https://www.jember.de/
- Concept International — ashby:concept — https://www.concept.biz/

## Moved to unresolved_companies.yaml this run

- Angsa Robotics — personio endpoint for 'angsa-robotics' is gone (404) — https://angsa-robotics.com
- FirmParking — personio endpoint for 'firmparking' is gone (404) — https://firmparking.de
