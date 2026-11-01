# ATS resolution report

- `config/companies.yaml` (fetched every run): 678
- `config/unresolved_companies.yaml` (not fetchable): 2026

## Fetchable, by vendor

- personio: 320
- ashby: 79
- greenhouse: 67
- workday: 51
- join: 48
- softgarden: 32
- smartrecruiters: 28
- recruitee: 20
- lever: 14
- workable: 10
- bamboohr: 5
- onlyfy: 4

## Not fetchable, by reason

- careers page has no supported ATS: 861
- no careers page found on the site: 592
- homepage blocks automated requests (HTTP 403): 92
- domain doesn't resolve (DNS) - site gone?: 86
- homepage TLS/SSL error: 85
- homepage unreachable (ConnectError): 40
- homepage timed out: 39
- homepage returns HTTP 404: 34
- rexx: no adapter yet: 19
- personio endpoint is gone (404): 17
- careers page uses successfactors (no adapter yet): 15
- teamtailor: no adapter yet: 13
- homepage returns HTTP 500: 10
- careers page has JSON-LD JobPosting data (generic-adapter candidate): 10
- careers page uses notion (no adapter yet): 8
- homepage returns HTTP 503: 7
- homepage returns HTTP 522: 6
- careers page uses cornerstone (no adapter yet): 6
- careers page uses factorial (no adapter yet): 6
- careers page uses hrworks (no adapter yet): 6
- careers page uses phenom (no adapter yet): 5
- homepage returns HTTP 402: 5
- homepage blocks automated requests (HTTP 429): 4
- careers page uses breezy (no adapter yet): 4
- careers page uses avature (no adapter yet): 4
- careers page uses zoho (no adapter yet): 4
- homepage returns HTTP 502: 3
- homepage returns HTTP 409: 3
- careers page uses talention (no adapter yet): 3
- softgarden endpoint is gone (404): 3
- careers page uses oracle (no adapter yet): 3
- careers page uses dvinci (no adapter yet): 3
- homepage returns HTTP 405: 3
- careers page uses umantis (no adapter yet): 2
- smartrecruiters endpoint is gone (404): 2
- detection crashed - see the run log: 2
- homepage blocks automated requests (HTTP 401): 2
- greenhouse endpoint is gone (404): 2
- careers page uses bite (no adapter yet): 2
- homepage returns HTTP 423: 1
- recruitee endpoint is gone (404): 1
- homepage unreachable (RemoteProtocolError): 1
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

## Moved to companies.yaml this run

- EASE — join:ease-systemsde — https://ease-systems.de/

## Moved to unresolved_companies.yaml this run

- Valtech — greenhouse endpoint for 'valtech' is gone (404) — https://www.valtech.com/
- QuantumDiamonds — personio endpoint for 'quantum-diamond' is gone (404) — https://www.quantumdiamonds.de/
- MSAID GmbH — personio endpoint for 'msaid' is gone (404) — https://www.msaid.de/career
- Sym GmbH — personio endpoint for 'sym' is gone (404) — https://sym.eco/
- ForTISS — personio endpoint for 'fortiss' is gone (404) — https://www.fortiss.org/
