# MT5 Portfolio Risk Planner

Aplicație desktop pentru estimarea bugetelor de risc și dimensionarea unor setări candidate DCA/RSI. Nu este un backtester al EA-urilor și nu poate garanta că un cont va respecta o limită de pierdere.

## Pornire și verificare

- Deschide `risk_calculator_app.pyw` cu Python pe Windows sau rulează `pyw risk_calculator_app.pyw`.
- Aplicația folosește biblioteca standard Python; nu are nevoie de pachete Python externe.
- Teste: `py -m unittest -v`.
- Calculatorul în terminal rămâne disponibil prin `py risk_calculator.py`.

## Date de contract și istoric MT5

1. În MT5 compilează și rulează `ExportMT5ContractSpecs.mq5` pentru specificațiile din Market Watch, inclusiv volumul maxim per ordin. Importă CSV-ul rezultat cu **Import MT5 contract CSV**.
2. Pentru istoric, compilează `ExportMT5History.mq5`, alege simbolul, timeframe-ul (recomandat `PERIOD_D1`) și numărul de bare, apoi rulează scriptul. Importă fișierul prin **Import MT5 OHLC history CSV**. Exportul include data/ora barei, OHLC, volume, spread-ul barei și, implicit, maximul/media spread-ului observat în update-uri Bid/Ask și numărul eșantioanelor valide.
3. Exportatoarele scriu în Common Files din MT5. În fișierul de istoric se păstrează simbolul brokerului; importul acceptă și mai multe simboluri în același CSV.
4. Se cer cel puțin 20 de bare zilnice valide. Barele intraday sunt agregate pe zi (high maxim, low minim și ultimul close).
5. **Suggest all robots (historical drawdown)** folosește OHLC MT5 pentru alocările care au istoric importat și cere Yahoo numai pentru alocările incomplete. Recomandarea folosește cea mai mare cădere istorică de la un maxim la un minim ulterior. **Fetch Yahoo data for all** înlocuiește explicit istoricul local cu datele Yahoo acolo unde Yahoo returnează istoric.

Prețurile Yahoo sunt doar fallback/referință și pot diferi de CFD-ul brokerului. Valoarea punctului, valuta contului, volumul minim și pasul de lot trebuie să corespundă exact contractului MT5. Istoricul MT5 este mai apropiat de instrumentul tranzacționat, dar tot nu prezice prețul sau execuția viitoare.

## Costuri și model istoric

În fila **Robot settings** poți introduce spread minim și slippage în puncte, un comision round-turn comun de fallback și, opțional, un comision per simbol în valuta contului per 1.00 lot. Când este completat, comisionul per simbol înlocuiește fallback-ul pentru acel simbol; când este gol, se folosește fallback-ul comun. Comisionul per simbol poate fi introdus în contractul simbolului sau citit din coloana opțională `commission_per_lot` din CSV-ul de contracte. Exportatorul MT5 nu poate determina comisionul brokerului; verifică și completează-l conform condițiilor contului.

Spread-ul din setări este pragul de bază pentru toate alocările. Dacă istoricul MT5 importat are `spread_max_points`, plannerul prioritizează această valoare, agregă maximul zilnic pe simbol și folosește valoarea mai mare dintre spread-ul observat și pragul introdus. Fișierele vechi rămân compatibile prin coloana `spread`. Pentru drawdown peak-to-trough folosește maximul observat în întregul istoric. Spread-ul Yahoo nu este disponibil; fără coloana MT5 rămâne valoarea introdusă manual.

`spread_max_points` și `spread_avg_points` sunt calculate din update-urile de tick care conțin Bid/Ask (`COPY_TICKS_INFO`) în intervalul barei. Media este doar informativă și nu intră în calculul recomandării; riscul folosește maximul, nu media. `spread_sample_count` arată câte cotații Bid/Ask valide au fost folosite, iar zero înseamnă că exportul a revenit la valoarea spread-ului barei (`spread`). Numărul de update-uri nu garantează că toate spike-urile au fost observate: lipsa istoricului de tick-uri, limitările brokerului și update-urile dintre bare pot omite valori extreme. Exportul poate dura mai mult deoarece citește tick-urile pentru fiecare bară. Verifică spread-ul și comisionul pentru fiecare CFD; în lipsa unor valori pe simbol, câmpurile comune trebuie setate conservator.

Recomandările limitează `Risk`/lotul inițial la `SYMBOL_VOLUME_MAX` când contractul MT5 importat include `max_lot`. Limita este per ordin și nu reprezintă plafonul volumului total simultan al gridului. Dacă fișierul vechi nu conține această coloană, se poate completa manual sau recomandarea nu are un plafon broker pentru volum maxim. Marja disponibilă și volumul total permis de cont nu sunt încă modelate.

Modul **Historical peak-to-trough drawdown** folosește cel mai mare declin de la un maxim zilnic la minimul ulterior, pe toată perioada importată. Pentru stresul grid, presupune conservator că pozițiile acumulate rămân deschise până la minim și nu creditează închideri Take Profit intermediare. Acesta este modul implicit pentru sugestia agregată, fiind potrivit pentru corecții ample într-o piață bullish. Modul separat **Historical max daily range** păstrează comparația mai puțin severă bazată pe șocuri zilnice independente.

Niciunul dintre moduri nu este un backtest al EA-ului: plannerul nu cunoaște regulile efective de intrare RSI, pozițiile deja deschise, Take Profit-ul, spread-ul din fiecare tick, swap-ul, execuția, gap-urile viitoare sau dacă EA-ul respectă setările recomandate. Pentru RSI, riscul este aproximat ca un grid de poziții la distanțele și multiplicatorul introduse, nu ca o simulare a semnalelor RSI. Fără sursele EA-urilor nu se poate confirma compatibilitatea parametrilor `.set` sau preveni redeschiderea pozițiilor de către robot. Validează scenariile în Strategy Tester și pe demo înainte de folosire.

Recomandarea folosește volume fixe, multiplicator 1.0 și maximum 80% din bugetul de risc configurat. În modul peak-to-trough, aceeași limită de risc este aplicată întregului episod, fără a presupune că pierderea permisă se resetează zilnic — o presupunere deliberat conservatoare. Valorile Step, Take Profit și pragurile RSI rămân decizii de strategie și trebuie backtestate separat. Alocările din raportul agregat sunt presupuse a suferi simultan șocurile lor istorice cele mai nefavorabile.

## Export `.set`

**Export .set template** produce un fișier candidate după generarea setărilor. Numele input-urilor și ordinea enum-urilor sunt deduse din lista de parametri furnizată; sursele EA-urilor și un preset real nu sunt în repository pentru a verifica identificatorii efectivi. Verifică fiecare câmp în fereastra Inputs a EA-ului înainte de încărcare și nu folosi presetul direct pe cont live. Exportul nu demonstrează compatibilitatea cu un EA necunoscut.

## Guard de equity pentru MT5

`MT5EquityRiskGuard.mq5` este un EA separat care verifică equity-ul pe timer, pune un lock în Terminal Global Variables și încearcă să închidă pozițiile și ordinele pending gestionate când limita zilnică sau limita totală este atinsă.

- Setează `InpDailyLossLimitCash` în valuta contului și `InpDailyResetHour` după ora serverului brokerului / resetul firmei prop.
- La prima instalare completează `InpDailyStartingEquity` cu equity-ul de la începutul zilei preluat din platforma firmei prop. Guard-ul refuză să ghicească această valoare.
- Pentru limita totală, configurează împreună `InpInitialAccountBalance` și `InpOverallLossLimitCash`.
- `InpManagedMagicNumbers="*"` gestionează toate pozițiile și ordinele din cont. Pentru o listă restrânsă folosește numere separate prin virgulă; pozițiile manuale sau ale altor EA-uri pot rămâne neprotejate.
- Variabila comună publicată este `MT5_RISK_GUARD_LOCKED_<login>` (sau sufixul ales plus login): valoarea `1` înseamnă oprit, `0` înseamnă că guard-ul funcționează și nu a declanșat limita. EA-urile cooperante trebuie să trateze și variabila inexistentă drept „oprit” și să o citească înaintea fiecărei intrări.
- La detașare, indisponibilitate a timpului serverului sau eroare de inițializare, guard-ul lasă lock-ul activ pentru a nu semnala fals că riscul este protejat. Lock-ul total rămâne persistent până la resetarea manuală, după reconcilierea pierderii.
- Dacă MT5/EA-ul este offline la resetul zilnic, guard-ul rămâne închis până când se furnizează manual equity-ul de început de zi și se reatașează.

Guard-ul nu poate împiedica un EA necooperant să redeschidă poziții după ce pozițiile curente au fost închise. Întreruperile MT5/VPS, erorile de broker, execuția parțială, gap-urile și slippage-ul pot depăși limita. Compilează și testează guard-ul și integrarea pe demo înainte de orice utilizare reală.

## Scenarii

Scenariile JSON v12 salvează alocările, datele de contract (inclusiv override-urile opționale per simbol), snapshot-ul de preț, sursa stresului istoric, barele MT5 importate (inclusiv spread-ul zilnic și numărul de eșantioane tick, dacă sunt disponibile) și costurile. Barele salvate sunt snapshot-uri; reimportă sau reîmprospătează datele înainte de a folosi o recomandare nouă. Formatele de scenariu mai vechi sunt migrate la încărcare.
