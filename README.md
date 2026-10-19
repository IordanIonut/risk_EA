# MT5 Portfolio Risk Planner

Aplicație desktop pentru estimarea bugetelor de risc și dimensionarea unor setări candidate DCA/RSI. Nu este un backtester al EA-urilor și nu poate garanta că un cont va respecta o limită de pierdere.

## Pornire și verificare

- Deschide `risk_calculator_app.pyw` cu Python pe Windows sau rulează `pyw risk_calculator_app.pyw`.
- Aplicația folosește biblioteca standard Python; nu are nevoie de pachete Python externe.
- Teste: `py -m unittest -v`.
- Calculatorul în terminal rămâne disponibil prin `py risk_calculator.py`.

În terminal, plafonul lotului este afișat cu precizia Decimal calculată, fără rotunjire suplimentară la patru zecimale. Rotunjește în jos la pasul de volum și verifică volumul minim/maxim al brokerului; terminalul nu importă aceste limite. Pierderea pentru recomandarea selectată este calculată la plafonul lotului, înainte de rotunjirea la pasul brokerului, nu la 1 lot. Modul de căutare cere o mișcare adversă pozitivă; verificarea cu mișcare zero nu determină un plafon de lot, deoarece calculatorul din terminal nu include costurile de execuție.

Step Value și conversia puncte per pip trebuie să fie fiecare strict pozitive, înainte de conversie; două valori negative nu formează un pas valid chiar dacă produsul lor este pozitiv. Configurația propusă în terminal cere și Take Profit Value strict pozitiv, atât în pips, cât și procentual. Valorile valide sunt păstrate, nu optimizate automat.

Motorul de calcul respinge explicit capitalul și limitele de pierdere nefinite (`NaN`, infinit), inclusiv capitalul alocărilor. Numărul maxim de tranzacții, limita candidaților și lungimea minimă a istoricului trebuie să fie întregi strict pozitivi; valorile fracționare sau booleene nu sunt convertite implicit. Aceste verificări se aplică și apelurilor directe ale funcțiilor Python, nu doar formularului.

## Alocări multiple pe același simbol

Poți avea mai multe instanțe cu același simbol, robot și ticker. Selectorul afișează și identificatorul intern al alocării, pentru a păstra fiecare instanță selectabilă separat. Contractul, capitalul și Magic Number-ul atribuit la generare rămân separate. Raportul indică identificatorul, capitalul și bugetul fiecărei alocări; mesajele despre date lipsă identifică instanța afectată.

Scenariile păstrează selecția după poziția alocării în listă, inclusiv pentru instanțe cu nume identice. Identificatorii afișați sunt locali aplicației și se pot schimba după reîncărcare; nu sunt Magic Numbers și nu sunt exportați ca parametri EA. Step, Take Profit și celelalte setări comune ale formularului nu devin preseturi independente per instanță.

## Date de contract și istoric MT5

1. În MT5 compilează și rulează `ExportMT5ContractSpecs.mq5` pentru specificațiile din Market Watch, inclusiv volumul maxim per ordin. Importă CSV-ul rezultat cu **Import MT5 contract CSV**.
2. Pentru istoric, compilează `ExportMT5History.mq5`, alege simbolul, timeframe-ul (recomandat `PERIOD_D1`) și numărul de bare, apoi rulează scriptul. Importă fișierul prin **Import MT5 OHLC history CSV**. Exportul include data/ora barei, OHLC, volume, spread-ul barei și, implicit, maximul/media spread-ului observat în update-uri Bid/Ask și numărul eșantioanelor valide.
3. Exportatoarele scriu în Common Files din MT5. În fișierul de istoric se păstrează simbolul brokerului; importul acceptă și mai multe simboluri în același CSV.
4. Se cer cel puțin 20 de bare zilnice valide. Barele intraday sunt agregate pe zi (open din prima bară cronologică, high maxim, low minim și ultimul close), inclusiv când rândurile CSV nu sunt ordonate. Open, când există, și close trebuie să fie în intervalul low–high al fiecărei bare, înainte de agregare.
5. **Suggest all robots (historical drawdown)** folosește OHLC MT5 pentru alocările care au istoric importat și cere Yahoo numai pentru alocările incomplete. Recomandarea folosește cea mai mare cădere istorică de la un maxim la un minim ulterior. **Fetch Yahoo data for all** înlocuiește explicit istoricul local cu datele Yahoo acolo unde Yahoo returnează istoric.

Importul respinge rândurile trunchiate, coloanele cu nume duplicate și timestamp-urile duplicate pentru același simbol, în loc să aleagă arbitrar un close sau să numere de două ori eșantioanele de spread. Când coloana `timeframe` este completată, nu amesteca timeframe-uri diferite pentru același simbol în același fișier. Simboluri diferite pot avea același timestamp. Data/ora trebuie exprimată în timpul local al brokerului, fără `Z` sau offset de fus orar; orele invalide nu sunt înlocuite automat cu miezul nopții.

Prețurile Yahoo sunt doar fallback/referință și pot diferi de CFD-ul brokerului. Valoarea punctului, valuta contului, volumul minim și pasul de lot trebuie să corespundă exact contractului MT5. Istoricul MT5 este mai apropiat de instrumentul tranzacționat, dar tot nu prezice prețul sau execuția viitoare.

La importul contractelor, `profit_currency` nu identifică valuta valorii punctului: valuta profitului instrumentului poate diferi de valuta contului în care brokerul raportează valoarea tick-ului. Folosește `account_currency`, `point_value_currency`, `account_currency_for_point_value` sau `contract_currency` pentru valuta valorii punctului. Un CSV vechi care conține numai `profit_currency` lasă acest câmp necompletat; completează coloana corectă și reimportă înainte de a genera recomandări.

Importul contractelor respinge coloane duplicate după normalizarea numelor, rânduri incomplete și coloane suplimentare fără antet. Dacă există mai multe coloane echivalente pentru același câmp, valorile completate trebuie să coincidă: `1` și `1.00` sunt echivalente, dar valori diferite sau invalide opresc importul cu numărul rândului și câmpul afectat. O celulă goală poate folosi o altă coloană echivalentă disponibilă. Formatele cu separator virgulă, punct și virgulă sau tab rămân acceptate.

Descărcările Yahoo întârziate nu sunt aplicate unei alocări noi care a înlocuit una eliminată sau unui scenariu reîncărcat. Încărcarea unui scenariu anulează sugestia automată de portofoliu aflată în așteptare și efectele cererii Yahoo active: rezultatele și finalizarea acelei cereri nu modifică datele, raportul sau mesajul de stare al noului scenariu și nu afișează avertizări pentru vechea cerere. Cererea de rețea deja pornită poate continua până la final; butoanele de descărcare rămân dezactivate până atunci, după care poți porni o cerere nouă. Verificarea periodică a răspunsurilor se oprește după finalizare.

O actualizare Yahoo înlocuiește perechea existentă cotație–istoric numai când sunt disponibile ambele rezultate. Dacă istoricul nu poate fi descărcat și există deja o pereche completă Yahoo sau MT5, aceasta este păstrată; o cotație nouă nu este combinată automat cu istoricul vechi. Fără istoric existent, cotația disponibilă poate fi păstrată pentru modurile manuale, dar modul istoric rămâne indisponibil. O descărcare incompletă afișează avertizarea și nu regenerează automat recomandări; poți reîncerca actualizarea sau genera explicit din datele păstrate.

Istoricul Yahoo este respins dacă seriile high/low/close nu au aceeași lungime ca seria timestamp-urilor sau dacă unei bare îi lipsește un preț. Barele incomplete nu sunt eliminate în tăcere, deoarece ar putea ascunde un episod advers. Timestamp-urile invalide sunt raportate cu poziția barei; datele duplicate sau neordonate sunt respinse. Regula celor minimum 20 de bare nu justifică ignorarea barelor invalide din răspuns. În aceste cazuri se aplică protecția pentru actualizări incomplete de mai sus.

Când prețul curent Yahoo lipsește din metadate, fallback-ul acceptă numai o listă de cotații cu o listă `close` și folosește ultimul close diferit de `null`. Un text sau un obiect nu este interpretat ca serie de prețuri. Ora cotației, dacă este furnizată, trebuie să fie un timestamp numeric valid; absența ei este afișată ca `time unavailable`, iar o valoare invalidă oprește cererea cu o eroare explicită.

La încărcarea unui scenariu cu bare MT5, toate statisticile istorice sunt recalculate din acele bare: șocurile zilnice în ambele direcții, datele lor, numărul și perioada barelor, drawdown-ul și raliul. Valorile rezumative salvate nu înlocuiesc istoricul efectiv. Pentru Yahoo, unde scenariul păstrează doar statisticile, acestea rămân un snapshot care trebuie actualizat înainte de utilizare.

Scenariile sunt validate înainte de salvare, cu aceleași reguli folosite la încărcare. Dacă validarea sau înlocuirea fișierului eșuează, apare o eroare, fișierul existent nu este înlocuit și calea scenariului curent nu este schimbată. Datele incomplete care sunt permise la încărcare, precum un Take Profit încă necompletat, pot fi păstrate; valorile invalide trebuie corectate înainte de salvare.

Un istoric plat poate fi salvat și reîncărcat cu stres zilnic zero și fără dată de observare pentru direcția respectivă. Pentru un stres pozitiv este obligatorie o dată în perioada istoricului; valorile negative sunt respinse. Păstrarea istoricului cu stres zero nu înseamnă că aplicația poate dimensiona o recomandare istorică din el și nu dovedește absența riscului.

## Costuri și model istoric

În fila **Robot settings** poți introduce spread minim și slippage în puncte, un comision round-turn comun de fallback și, opțional, un comision per simbol în valuta contului per 1.00 lot. Când este completat, comisionul per simbol înlocuiește fallback-ul pentru acel simbol; când este gol, se folosește fallback-ul comun. Comisionul per simbol poate fi introdus în contractul simbolului sau citit din coloana opțională `commission_per_lot` din CSV-ul de contracte. Exportatorul MT5 nu poate determina comisionul brokerului; verifică și completează-l conform condițiilor contului.

Spread-ul din setări este pragul de bază pentru toate alocările. Dacă istoricul MT5 importat are `spread_max_points`, plannerul prioritizează această valoare, agregă maximul zilnic pe simbol și folosește valoarea mai mare dintre spread-ul observat și pragul introdus. Fișierele vechi rămân compatibile prin coloana `spread`. Pentru drawdown peak-to-trough folosește maximul observat în întregul istoric. Spread-ul Yahoo nu este disponibil; fără coloana MT5 rămâne valoarea introdusă manual.

Replay-ul zilnic validează costurile configurate înainte de aplicarea spread-ului istoric: spread-ul, slippage-ul și comisionul trebuie să fie finite și nenegative. Un spread istoric valid nu corectează implicit un spread configurat negativ sau nevalid; apelurile directe ale motorului primesc o eroare explicită.

Prioritatea coloanelor de spread se aplică fiecărui rând: `spread_max_points`, `max_spread_points`, `spread_points`, apoi `spread`. O celulă goală permite folosirea următoarei coloane disponibile; o valoare completată, dar invalidă, oprește importul și nu este ignorată.

`spread_max_points` și `spread_avg_points` sunt calculate din update-urile de tick care conțin Bid/Ask (`COPY_TICKS_INFO`) în intervalul barei. Media este doar informativă și nu intră în calculul recomandării; riscul folosește maximul, nu media. `spread_sample_count` arată câte cotații Bid/Ask valide au fost folosite, iar zero înseamnă că exportul a revenit la valoarea spread-ului barei (`spread`). Numărul de update-uri nu garantează că toate spike-urile au fost observate: lipsa istoricului de tick-uri, limitările brokerului și update-urile dintre bare pot omite valori extreme. Exportul poate dura mai mult deoarece citește tick-urile pentru fiecare bară. Verifică spread-ul și comisionul pentru fiecare CFD; în lipsa unor valori pe simbol, câmpurile comune trebuie setate conservator.

Recomandările limitează `Risk`/lotul inițial la `SYMBOL_VOLUME_MAX` când contractul MT5 importat include `max_lot`. Limita este per ordin și nu reprezintă plafonul volumului total simultan al gridului. Dacă fișierul vechi nu conține această coloană, se poate completa manual sau recomandarea nu are un plafon broker pentru volum maxim. Marja disponibilă și volumul total permis de cont nu sunt încă modelate.

Modul **Historical peak-to-trough drawdown** folosește cel mai mare declin de la un maxim zilnic la minimul ulterior, pe toată perioada importată. Pentru stresul grid, presupune conservator că pozițiile acumulate rămân deschise până la minim și nu creditează închideri Take Profit intermediare. Acesta este modul implicit pentru sugestia agregată, fiind potrivit pentru corecții ample într-o piață bullish. Modul separat **Historical max daily range** păstrează comparația mai puțin severă bazată pe șocuri zilnice independente.

După **Generate candidate settings**, dacă există bare zilnice MT5 și un Take Profit valid, aplicația rulează și o simulare cronologică generică a unei singure campanii de grid: începe la închiderea primei bare, adaugă poziții la pașii configurați, păstrează pozițiile peste zile și închide coșul când prețul atinge TP față de prețul mediu ponderat. Raportează rezultatul net modelat, drawdown-ul equity maxim, pierderea zilnică maximă, numărul maxim de poziții, închiderile TP și dacă prețul a depășit următorul nivel după `Max Trades`. Costurile round-turn configurate sunt scăzute la deschiderea fiecărei poziții; la final, pozițiile rămase sunt evaluate la ultimul close.

Simularea presupune intrări market la atingerea nivelului, nu ordine pending: dacă un gap advers trece de următoarea intrare, aceasta se execută la open, iar următorul nivel este recalculat de la prețul efectiv de intrare. Nu sunt inventate execuții la niveluri sărite de gap. Un gap favorabil care deschide dincolo de TP închide coșul la open, înainte de mișcările ulterioare ale zilei. Spread-ul, slippage-ul și comisionul rămân costuri cash aproximative, nu cotații Bid/Ask simulate.

Această simulare folosește traseul OHLC zilnic presupus „open, mișcarea adversă, cea favorabilă, close” (pentru long: open–low–high–close; pentru short: open–high–low–close). CSV-urile/scenariile vechi fără open rămân compatibile: se folosește close-ul precedent limitat la intervalul low–high al barei, iar raportul avertizează că execuția la gap este aproximată. Reimportă istoricul MT5 pentru a păstra open-ul real. Scenariile noi se salvează în versiunea 13, cu open opțional; încărcarea versiunilor 1–12 rămâne disponibilă.

Drawdown-ul maxim în bani păstrează vârful și minimul episodului respectiv; o recuperare ulterioară nu schimbă aceste date. Drawdown-ul procentual maxim este urmărit separat, fiecare scădere fiind raportată la vârful equity existent atunci, nu la un maxim ulterior. Cele două maxime pot proveni din episoade diferite. Pierderea zilnică folosește equity-ul de la închiderea barei precedente ca bază și include gap-ul și costurile intrărilor; nu implementează ora de reset sau regulile specifice unei firme prop.

Stresul static include și intrarea care se deschide exact la capătul mișcării adverse: pierderea ei de preț este zero în acel punct, dar costurile nu sunt zero. Și barele fără mișcare pot contribui la stres prin costurile de tranzacționare. Din acest motiv, numărul candidat de intrări sau lotul recomandat pot diferi de versiunile anterioare.

Calculul stresului static acumulează pierderile într-o singură parcurgere a intrărilor atinse, fără recalcularea fiecărui prefix al gridului. Aceasta reduce timpul pentru griduri mari fără schimbarea formulei, costurilor sau regulii de 80%. Numărul maxim de tranzacții încadrate în buget reprezintă capacitatea configurabilă în scenariul testat, nu numărul de poziții efectiv deschise: intrările dincolo de mișcarea testată nu adaugă pierdere.

Barele intraday sunt în prezent agregate pe zi înainte de simulare; deci nu este încă replay M1/M5 și nu poate stabili ordinea reală a mișcărilor în interiorul zilei. După atingerea TP, campania rămâne inactivă pentru restul istoricului; nu sunt generate cicluri noi, deoarece semnalele și condițiile reale ale EA-ului sunt necunoscute. Rezultatul nu modelează marja, swap-ul, execuția reală sau semnalele RSI și nu este echivalent cu Strategy Tester.

Nici simularea, nici modurile de stres nu reproduc complet EA-ul: plannerul nu cunoaște regulile efective de intrare RSI, pozițiile deja deschise, spread-ul din fiecare tick, swap-ul, execuția, gap-urile viitoare sau dacă EA-ul respectă setările recomandate. Pentru RSI, riscul este aproximat ca un grid de poziții la distanțele și multiplicatorul introduse, nu ca o simulare a semnalelor RSI. Fără sursele EA-urilor nu se poate confirma compatibilitatea parametrilor `.set` sau preveni redeschiderea pozițiilor de către robot. Validează scenariile în Strategy Tester și pe demo înainte de folosire.

Recomandarea folosește volume fixe, multiplicator 1.0 și maximum 80% din bugetul de risc configurat. În modul peak-to-trough, aceeași limită de risc este aplicată întregului episod, fără a presupune că pierderea permisă se resetează zilnic — o presupunere deliberat conservatoare. Valorile Step, Take Profit și pragurile RSI rămân decizii de strategie și trebuie backtestate separat. Alocările din raportul agregat sunt presupuse a suferi simultan șocurile lor istorice cele mai nefavorabile.

Toate modurile de generare, inclusiv **Target price** și **Adverse move (%)**, cer valuta contului și valoarea punctului în aceeași valută. Aplicația nu convertește automat valoarea punctului; un contract cu valută lipsă sau diferită trebuie corectat înainte de generare. Raportul agregat respectă plafonul `max_lot` și pasul de volum inclusiv în modurile manuale.

Numărul **Max Trades candidates** limitează acum și căutarea automată istorică, pentru alocarea selectată și pentru raportul agregat. Pentru long, procentul advers trebuie să fie pozitiv și sub 100%, iar prețul țintă trebuie să fie pozitiv. Pentru short, o creștere adversă poate fi de 100% sau mai mare; această valoare este acceptată atât manual, cât și din istoricul disponibil. După o generare eșuată, rezultatul anterior este șters pentru a nu fi confundat cu o recomandare recalculată.

## Export `.set`

**Export .set template** produce un fișier candidate după generarea setărilor. Numele input-urilor și ordinea enum-urilor sunt deduse din lista de parametri furnizată; sursele EA-urilor și un preset real nu sunt în repository pentru a verifica identificatorii efectivi. Verifică fiecare câmp în fereastra Inputs a EA-ului înainte de încărcare și nu folosi presetul direct pe cont live. Exportul nu demonstrează compatibilitatea cu un EA necunoscut.

Copierea unui raport generat și exportul verifică dacă setările, portofoliul, alocarea selectată, cotațiile și istoricul corespund încă acelui calcul. Dacă s-au schimbat sau textul raportului a fost editat, operația este blocată cu un mesaj de regenerare. Rulează din nou **Generate candidate settings** după modificări; editarea textului afișat nu recalculează riscul și nu poate înlocui generarea.

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
