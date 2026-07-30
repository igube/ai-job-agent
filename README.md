# AI Job Agent

Lokalny agent, który raz dziennie przeszukuje pięć polskich portali pracy, ocenia
każdą ofertę względem mojego CV i przedstawia wynik w dashboardzie.

**Wszystko działa lokalnie — bez klucza API i bez kosztów.** Ocenę wykonuje model
`qwen2.5:14b-instruct` uruchomiony przez Ollamę na własnym GPU.


## Screeny z działania agenta
<img width="2559" height="1439" alt="image" src="https://github.com/user-attachments/assets/e2a672c4-7f16-435d-8a7a-13112836116b" />
<img width="2559" height="1439" alt="image" src="https://github.com/user-attachments/assets/cbffa3fa-f9dc-402c-97eb-7cf6262c5f25" />
<img width="2559" height="1439" alt="image" src="https://github.com/user-attachments/assets/77af88c5-d997-4cd5-8c8a-7f1664053e05" />

## Co robi

```
CV (PDF)  ──►  parser offline  ──►  strukturyzacja (LLM)  ──►  profil kandydata
                                                                     │
5 portali  ──►  fetch + dedup  ──►  filtr poziomu i lokalizacji  ──►  ocena LLM
                                                                     │
                                                          dashboard z rankingiem
```

| Etap | Co się dzieje | Model |
|---|---|---|
| 1 | PDF → tekst → sekcje i dane kontaktowe | brak (regex) |
| 2 | Sekcje → struktura (doświadczenie, projekty, języki) | lokalny |
| 3 | Pobranie ofert z 5 portali + deduplikacja | brak |
| 4 | Filtr poziomu i lokalizacji, potem ocena 5-wymiarowa | lokalny |
| 5 | Agent spina etapy i podsumowuje | lokalny |
| 6 | Dashboard (Streamlit) | brak |

## Źródła ofert

Żaden z tych portali nie udostępnia publicznej dokumentacji API — każde źródło
wymagało własnego podejścia.

| Portal | Jak pobieram | Uwagi |
|---|---|---|
| justjoin.it | prywatne API `/api/candidate-api/offers` | kategoria `ai`, paginacja kursorowa |
| rocketjobs.pl | to samo API (ten sam operator) | brak kategorii AI → filtr trafności |
| olx.pl | publiczne API `/api/v1/offers` | najbogatsze opisy (2–4 tys. znaków) |
| theprotocol.it | `__NEXT_DATA__` z SSR | filtry poziomu w ścieżce URL |
| pracuj.pl | Playwright (Cloudflare) | limit 1×/24h, wymuszony w kodzie |

## Napotkane problemy

Te fragmenty powstały w reakcji na konkretne awarie.

**Filtr trafności ma dwa poziomy, bo oferta z branży fashion dostała 85% dopasowania.**
Ogłoszenie *„Młodszy Specjalista ds. Rozwoju Marki"* przechodziło filtr, bo w opisie
padło słowo „automatyzacja", a potem model wysoko je ocenił — kandydat faktycznie ma
doświadczenie marketingowe. Rozwiązanie: terminy silne (`machine learning`, `LLM`)
liczą się wszędzie, słabe (`AI`, `automatyzacja`) tylko w tytule.
→ [`relevance.py`](src/job_agent/job_scraping/relevance.py)

**Parametru filtra w pracuj.pl nie da się odgadnąć.**
Strzelanie w `p=1,17` dawało puste wyniki, choć parametr pojawiał się w `searchCriteria`.
Właściwą odpowiedź (`et=1,3,17`) znalazłem dopiero klikając realny interfejs w Playwrighcie
i czytając URL po zatwierdzeniu filtrów.
→ [`pracujpl.py`](src/job_agent/job_scraping/sources/pracujpl.py)

**Ocena rozbita na 5 wymiarów, bo jedna liczba dawała klastry.**
Przy prośbie o „wynik 0–100" model zwracał ciągle te same okrągłe wartości (65, 65, 50)
dla bardzo różnych ofert. Teraz ocenia osobno wymagania, poziom, dziedzinę, rozwój
i warunki, a wynik końcowy to ważona średnia liczona w kodzie — dzięki temu jest
granularny i **wyjaśnialny**: widać, że oferta ma 46% bo `poziom: 18`, mimo `warunki: 92`.
→ [`ai_scorer.py`](src/job_agent/matching/ai_scorer.py)

**Poziom docelowy wynika z CV, nie jest zapisany na sztywno.**
Student bez komercyjnego doświadczenia dostaje priorytet na staże, bo oferty „junior"
i tak zwykle wymagają Kubernetesa. Jeśli staży jest za mało, pula automatycznie
poszerza się o junior. Inne CV → inny target, bez zmiany kodu.
→ [`level_inference.py`](src/job_agent/matching/level_inference.py)

**Lokalny model 14B jest zawodny w tool-callingu.**
Gubił format wywołań, halucynował nazwy argumentów (`fetch_jobs(top=...)`), a gdy
dostał parametr `top` — wpisywał w niego 5 i cicho odrzucał większość listy.
Rozwiązanie: retry gdy przebieg nie wywołał żadnego narzędzia, przechwytywanie
`TypeError` i oddawanie błędu modelowi do samopoprawy, oraz usunięcie parametrów,
którymi psuł wyniki.
→ [`agent.py`](src/job_agent/agent/agent.py)

**Portal z ochroną antybotową traktuję jak gościa, nie jak cel.**
pracuj.pl jest za Cloudflare. Limit 1×/24h jest wymuszony plikiem stanu, nie dobrą
wolą — dowolna liczba uruchomień dashboardu w ciągu dnia korzysta z cache.
LinkedIn **świadomie pominąłem**: jego regulamin wprost zakazuje automatycznego
zbierania danych, w przeciwieństwie do pozostałych źródeł.
→ [`rate_limit.py`](src/job_agent/job_scraping/rate_limit.py)

## Uruchomienie

Wymagania: Python 3.12, [Ollama](https://ollama.com).

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-ai.txt -r requirements-scraping.txt -r requirements-dashboard.txt
.venv\Scripts\python -m playwright install chromium
ollama pull qwen2.5:14b-instruct
```

Wgraj swoje CV jako `cv/cv.pdf`, potem:

```bash
.venv\Scripts\python scripts\parse_cv.py     # PDF -> JSON (offline)
.venv\Scripts\python scripts\enrich_cv.py    # JSON -> struktura (lokalny model)
.venv\Scripts\streamlit run scripts\dashboard.py
```

Dashboard startuje pod `http://localhost:8501`. Przycisk „Uruchom agenta" sam
podnosi Ollamę, jeśli nie działa.

## Testy

```bash
.venv\Scripts\python -m pytest
```

32 testy pokrywają część deterministyczną — filtr trafności, wnioskowanie poziomu,
dopasowanie lokalizacji i deduplikację. Warstwa LLM jest celowo poza testami
(niedeterministyczna), ale wszystko, co ją otacza, jest sprawdzalne.

Testy od razu zarobiły na siebie: wyłapały, że regex nie rozpoznawał odmiany
„sztuczn**ą** inteligencj**ę**" (biernik) — filtr przepuszczał tylko mianownik i dopełniacz.

## Liczby

- **5** portali, ~650 ofert w jednym przebiegu
- **~60 s** pełny cykl (model w VRAM), ~3 min przy zimnym starcie
- **0 zł** kosztów — model lokalny, RTX 5070 Ti
- **2800** linii Pythona

## Świadome ograniczenia

- **Warstwa agentowa jest cienka.** Agent ma dwa narzędzia i wywołuje je w stałej
  kolejności — prawdziwa wartość siedzi w ocenie ofert. Sensowna agencyjność
  zaczęłaby się przy celu typu „znajdź 5 ofert wartych aplikacji w tym tygodniu",
  gdzie trzeba decydować o poszerzaniu kryteriów.
- **Brak historii przebiegów.** Każde uruchomienie zaczyna od zera — nie wiadomo,
  które oferty są nowe od wczoraj.
- **Brak pomiaru jakości ocen.** Nie ma zbioru referencyjnego, więc nie wiem,
  w ilu procentach model zgadza się z moją własną oceną.
- **Model 14B waha się między przebiegami** — wynik liczbowy różnicuje dobrze,
  ale sam werdykt (polecam/rozważ) bywa niestabilny.

## Licencja

MIT
