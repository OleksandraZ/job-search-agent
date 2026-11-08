# ATS resolution report

- `config/companies.yaml` (fetched every run): 679
- `config/unresolved_companies.yaml` (not fetchable): 2025

## Fetchable, by vendor

- personio: 320
- ashby: 81
- greenhouse: 66
- workday: 50
- join: 49
- softgarden: 32
- smartrecruiters: 28
- recruitee: 19
- lever: 15
- workable: 10
- bamboohr: 5
- onlyfy: 4

## Not fetchable, by reason

- careers page has no supported ATS: 857
- no careers page found on the site: 597
- homepage blocks automated requests (HTTP 403): 101
- domain doesn't resolve (DNS) - site gone?: 88
- homepage TLS/SSL error: 87
- homepage unreachable (ConnectError): 36
- homepage returns HTTP 404: 34
- homepage timed out: 31
- rexx: no adapter yet: 20
- careers page uses successfactors (no adapter yet): 15
- personio endpoint is gone (404): 14
- teamtailor: no adapter yet: 13
- careers page has JSON-LD JobPosting data (generic-adapter candidate): 10
- homepage returns HTTP 500: 8
- careers page uses hrworks (no adapter yet): 8
- careers page uses cornerstone (no adapter yet): 7
- careers page uses notion (no adapter yet): 7
- homepage blocks automated requests (HTTP 429): 5
- careers page uses phenom (no adapter yet): 5
- homepage returns HTTP 503: 5
- homepage returns HTTP 402: 5
- careers page uses avature (no adapter yet): 5
- careers page uses factorial (no adapter yet): 5
- homepage returns HTTP 522: 4
- careers page uses zoho (no adapter yet): 4
- recruitee endpoint is gone (404): 3
- homepage returns HTTP 409: 3
- homepage blocks automated requests (HTTP 401): 3
- careers page uses talention (no adapter yet): 3
- careers page uses breezy (no adapter yet): 3
- softgarden endpoint is gone (404): 3
- careers page uses oracle (no adapter yet): 3
- careers page uses dvinci (no adapter yet): 3
- homepage returns HTTP 405: 3
- greenhouse endpoint is gone (404): 3
- careers page uses umantis (no adapter yet): 2
- smartrecruiters endpoint is gone (404): 2
- detection crashed - see the run log: 2
- careers page uses bite (no adapter yet): 2
- homepage returns HTTP 423: 1
- homepage unreachable (RemoteProtocolError): 1
- homepage returns HTTP 502: 1
- removed by hand 2026-10-23 - domain now redirects to a gambling shop (ecommercegenius.shop): 1
- homepage returns HTTP 525: 1
- careers page uses hibob (no adapter yet): 1
- lever endpoint is gone (404): 1
- careers page uses phenom, successfactors (no adapter yet): 1
- homepage returns HTTP 410: 1
- homepage unreachable (TooManyRedirects): 1
- duplicate of CARSYNC (VISPIRON) - motum's site redirects to carsync.de; jobs fetched via JOIN vispiron-gmbh (checked by hand 2026-10-23): 1
- careers page uses notion, pinpoint (no adapter yet): 1
- careers page uses pinpoint (no adapter yet): 1
- careers page uses teamtailor (no adapter yet): 1
- removed by hand 2026-10-23 (not a fit): 1
- workday endpointtenant': 'nxp', 'wd_host': 'wd3', 'site': 'careers'}' is gone (404): 1

## Moved to companies.yaml this run

- FirmParking — personio:firmparking — https://firmparking.de
- MediPulse — join:medipulsede — https://www.medipulse.de
- Alasco — lever:alasco — https://www.alasco.de/
- Starforge GmbH — ashby:starforge — https://starforge.energy
- Valtech — greenhouse:valtech — https://www.valtech.com/
- QuantumDiamonds — ashby:quantumdiamonds — https://www.quantumdiamonds.de/

## Moved to unresolved_companies.yaml this run

- Parloa — greenhouse endpoint for 'parloa' is gone (404) — https://www.parloa.com
- Urban Sports Club — greenhouse endpoint for 'urbansportsclub' is gone (404) — https://urbansportsclub.com
- XO Life — personio endpoint for 'xolife' is gone (404) — https://xolife.jobs.personio.de/
- Munevo — recruitee endpoint for 'munevo' is gone (404) — https://munevo.com/en
- NXP Semiconductors Germany — workday endpoint for '{'tenant': 'nxp', 'wd_host': 'wd3', 'site': 'careers'}' is gone (404) — https://www.nxp.com/company/about-nxp/careers:CAREERS
