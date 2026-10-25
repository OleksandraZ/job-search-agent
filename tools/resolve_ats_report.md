# ATS resolution report

- `config/companies.yaml` (fetched every run): 682
- `config/unresolved_companies.yaml` (not fetchable): 2022

## Fetchable, by vendor

- personio: 324
- ashby: 79
- greenhouse: 68
- workday: 51
- join: 47
- softgarden: 32
- smartrecruiters: 28
- recruitee: 20
- lever: 14
- workable: 10
- bamboohr: 5
- onlyfy: 4

## Not fetchable, by reason

- careers page has no supported ATS: 857
- no careers page found on the site: 590
- homepage blocks automated requests (HTTP 403): 93
- domain doesn't resolve (DNS) - site gone?: 89
- homepage TLS/SSL error: 85
- homepage unreachable (ConnectError): 41
- homepage timed out: 37
- homepage returns HTTP 404: 33
- rexx: no adapter yet: 20
- teamtailor: no adapter yet: 14
- careers page uses successfactors (no adapter yet): 14
- personio endpoint is gone (404): 14
- careers page has JSON-LD JobPosting data (generic-adapter candidate): 11
- homepage returns HTTP 503: 10
- homepage returns HTTP 500: 9
- careers page uses notion (no adapter yet): 8
- careers page uses cornerstone (no adapter yet): 7
- careers page uses factorial (no adapter yet): 6
- careers page uses hrworks (no adapter yet): 6
- careers page uses phenom (no adapter yet): 5
- homepage returns HTTP 402: 5
- homepage blocks automated requests (HTTP 429): 4
- homepage returns HTTP 522: 4
- careers page uses breezy (no adapter yet): 4
- softgarden endpoint is gone (404): 4
- careers page uses avature (no adapter yet): 4
- careers page uses zoho (no adapter yet): 4
- homepage unreachable (RemoteProtocolError): 3
- homepage returns HTTP 409: 3
- homepage blocks automated requests (HTTP 401): 3
- careers page uses talention (no adapter yet): 3
- careers page uses oracle (no adapter yet): 3
- careers page uses dvinci (no adapter yet): 3
- homepage returns HTTP 405: 3
- careers page uses umantis (no adapter yet): 2
- recruitee endpoint is gone (404): 2
- detection crashed - see the run log: 2
- careers page uses bite (no adapter yet): 2
- smartrecruiters endpoint is gone (404): 1
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
- careers page uses pinpoint (no adapter yet): 1
- careers page uses teamtailor (no adapter yet): 1
- removed by hand 2026-10-23 (not a fit): 1

## Moved to companies.yaml this run

- Intel — workday:{'tenant': 'intel', 'wd_host': 'wd1', 'site': 'External'} — https://www.intel.de/
- NXP Semiconductors Germany — workday:{'tenant': 'nxp', 'wd_host': 'wd3', 'site': 'careers'} — https://www.nxp.com/
- Analog Devices Germany — ashby:analog — https://www.analog.com/
- ROHM Semiconductor Europe — personio:rohm-semiconductor — https://www.rohm.com/eu
- Disney Germany — workday:{'tenant': 'disney', 'wd_host': 'wd5', 'site': 'disneycareer'} — https://www.disney.de/
- BANKSapi GmbH — personio:banksapi — https://banksapi.de/
- sparkle gifts — ashby:sparkle — http://www.sparkle.gifts/
- SUMM AI GmbH — join:summ-ai — https://summ-ai.com/
- Cambrion — join:cambrionai — https://www.cambrion.ai/
- HolidayCheck Group — personio:holidaycheck — https://www.holidaycheckgroup.com/
- EDAG Engineering — workable:edag-uk — https://www.edag.com/
- TrustYou GmbH — join:trustyounet — http://www.trustyou.com
- Sym GmbH — personio:sym — https://sym.eco/
- Greenda — personio:greenda — https://greenda.ai/?source=munichstartupprofile
- Capmont — greenhouse:plume — https://www.cmont.com/
- amp sound branding — greenhouse:landor — https://ampsoundbranding.com/
- Terra Canis — personio:terra-canis-gmbh — https://www.terracanis.com/
- ForTISS — personio:fortiss — https://www.fortiss.org/
- European Medicines Agency (EMA) — ashby:ema — https://www.ema.europa.eu
- Institut für Arbeitsmarkt- und Berufsforschung (IAB) der Bundesagentur für Arbeit — personio:iab — https://www.iab.de

## Moved to unresolved_companies.yaml this run

- Rencore — personio endpoint for 'rencore' is gone (404) — https://rencore.com/en/company/career/
