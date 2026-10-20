# MT5 Portfolio Risk Planner

Aplicație desktop pentru estimarea bugetelor de risc și dimensionarea unor setări candidate DCA/RSI. Nu este un backtester al EA-urilor și nu poate garanta că un cont va respecta o limită de pierdere.

## Pornire și verificare

### Laptop Windows cu MT5 (inclusiv cont demo)

Aplicația și terminalul MT5 trebuie să ruleze pe **același laptop**; conectorul Python nu accesează prin rețea terminalul de pe alt calculator.

Cu acces la repository, pe laptopul nou:

```powershell
git clone https://github.com/IordanIonut/risk_EA.git
Set-Location .\risk_EA
.\Start-RiskPlanner.ps1 -Setup
.\Start-RiskPlanner.ps1 -Check
.\Start-RiskPlanner.ps1
```

Aceste comenzi presupun Git și Python 3.12 x64 instalate și modificările de mai jos publicate în repository. Pentru o clonă existentă, folosește `git pull --ff-only` înainte de `-Setup`; dacă ai modificări locale, rezolvă-le înainte de actualizare, fără a șterge portofoliul. Fișierele private din `data` nu sunt descărcate prin Git și nu trebuie publicate.

Workflow-ul GitHub Actions **Windows MT5 planner** verifică instalarea dependențelor, lansatorul în modul `-Check`, testele Tkinter și compilarea pe Windows/Python 3.12. Rulează la push/PR sau manual din Actions. Nu autentifică un cont MT5 și nu validează tranzacții sau conexiunea reală la broker.

1. Copiază folderul proiectului într-o locație în care poți scrie. Nu copia `.venv` sau `__pycache__`: mediul Python se recreează pe laptopul nou. Dacă vrei portofoliul și istoricul existente, transferă privat și folderul `data` (ignorat de Git), sau folosește **Save scenario / Load scenario**. Nu trimite datele contului într-un repository public.
2. Instalează **Python 3.12 pe 64 de biți**, cu Python Launcher și Tkinter, apoi terminalul MT5 al brokerului ales. Un cont demo este suficient pentru preluarea datelor disponibile; nu trebuie cumpărat un cont prop.
3. Deschide PowerShell în folderul proiectului și execută:

   ```powershell
   .\Start-RiskPlanner.ps1 -Setup
   ```

   Scriptul creează `.venv` și instalează dependențele din `requirements-mt5.txt`. Nu modifică instalarea globală Python. Dacă politica sistemului blochează scripturile, folosește metoda aprobată de administrator; scriptul nu schimbă politica de execuție.

4. Pornește MT5 și autentifică-te în contul demo pe serverul corect. Verifică denumirile exacte ale instrumentelor în **Market Watch** (de exemplu `US500.cash` poate fi diferit de `US500`). Pentru istoric lung, mărește **Tools > Options > Charts > Max bars in chart**, deschide graficele D1 și lasă terminalul să descarce istoricul. Serverul poate furniza mai puțin de cinci ani.
5. Pornește aplicația:

   ```powershell
   .\Start-RiskPlanner.ps1
   ```

6. În **Prop firm & account** introdu capitalul ipotetic și limitele prop. În **Portfolio** adaugă simbolurile exacte și procentele, apoi apasă **Connect MT5: get specs + 5y D1**. Indicatorul animat arată că operația este în curs. Conectarea manuală preia valuta contului MT5: aceasta trebuie să corespundă scenariului, deoarece valoarea punctului este exprimată în valuta contului brokerului, nu convertită arbitrar.
7. Verifică manual **points per EA pip**, Step, Take Profit și comisionul: MT5 nu furnizează convențiile robotului sau comisionul prin proprietățile simbolului. Datele primite se salvează local; următoarea pornire încearcă actualizarea surselor MT5 salvate.

`.\Start-RiskPlanner.ps1 -Check` verifică doar mediul Python și importul MetaTrader5, fără conectare sau tranzacții. Instalarea/folosirea efectivă a terminalului trebuie verificată pe laptopul destinație. Pentru mai multe terminale, deschide și verifică terminalul/contul dorit înainte de conectare; aplicația nu oferă încă un selector al executabilului MT5.

Conectorul plannerului citește date, nu trimite ordine și nu instalează robotul. Datele unui demo de la alt broker sunt potrivite pentru planificare, nu confirmă contractele sau execuția viitorului cont prop. Acest flux nu necesită activarea Algo Trading pentru plasarea de ordine.

- **Import prop rules from website...**, în **Prop firm & account**, permite introducerea unui link HTTPS către pagina oficială a programului. Extragerea locală, fără AI sau cheie API, caută perechi de procente daily/total în tabele HTML în engleză, afișează rândul sursă, URL-ul și data descărcării. Alege programul/etapa, verifică valorile și capitalul/valuta contului, apoi confirmă explicit înainte de aplicare. Pentru cont nou poți bifa folosirea întregului buget nominal; pentru cont existent trebuie completate bugetele cash efectiv rămase. **Apply limits + suggest robot settings** aplică limitele confirmate și pornește recomandarea existentă, care necesită și contractul brokerului, istoricul și parametrii strategiei. Candidații extrași se salvează local în `data\prop_website.json` și se restaurează în fereastra de import; limitele aplicate se salvează cu portofoliul. Nu sunt interpretate automat toate regulile firmei: trailing drawdown, fus orar/resetare zilnică, interdicții EA, corelații sau limita pe idee. Site-urile doar JavaScript, PDF-urile, tabelele verticale sau alte limbi pot necesita completare manuală. Eșecul extragerii nu modifică contul; funcția nu este un configurator universal sau o certificare de conformitate.
- În **Prop firm & account** este inclusă local o referință **SpiceProp Sweet / Spice 2 Step**, verificată la 20.10.2026, disponibilă fără internet. Tabelul pentru 25.000 EUR păstrează limitele zilnice de 5,5% / 4,5% / 4,5%, limita totală de 11% și țintele de 7,5% / 5% / fără țintă în funded. Sunt afișate sursele, capitalurile disponibile și avertizarea că 1.000 EUR nu aparține acestui program. Referința nu modifică automat contul și nu se actualizează online. Regula funded de 2% pe idee/expuneri corelate și resetarea zilnică specifică firmei rămân neverificate de model; confirmă regulile actuale cu firma.
- Deschide `risk_calculator_app.pyw` cu Python pe Windows sau rulează `pyw risk_calculator_app.pyw`.
- Fila **Prop firm & account** grupează capitalul, valuta, limita zilnică (procent sau sumă), limita zilnică rămasă și limita totală prop rămasă. Aceste valori se salvează automat local în `data\portfolio.json` și se restaurează la pornire, inclusiv din scenariile existente. Roboții și alocările rămân în **Portfolio**, iar setările în **Robot settings**. Limitele sunt introduse de utilizator conform regulilor firmei, nu preluate automat de la o firmă prop.
- Aplicația folosește biblioteca standard Python. Conectarea directă la MT5 este opțională și cere pachetul `MetaTrader5`.
- `data\portfolio.json` v15 salvează contul, alocările și setările robotului fără contracte MT5, cotații sau bare de piață duplicate. Override-urile introduse manual pentru convenția pip și comision per robot rămân în portofoliu. Pentru fiecare simbol, contractul MT5, cotația, stresul și barele D1 se păstrează în `data\<simbol>\market_data.json`, iar charturile pe timeframe în `data\<simbol>\charts\`. La startup se încarcă aceste fișiere; autosave-urile vechi v1–v14 se migrează automat după salvarea cache-ului. Folderul `data\` este ignorat de Git deoarece poate conține date private ale contului. Scenariile salvate manual rămân complete și portabile.
- La deschidere, după încărcarea portofoliului, aplicația reîmprospătează datele în fundal: Yahoo pentru alocările Yahoo/fără sursă, terminalul pentru sursa **MT5 terminal**, respectiv endpointul salvat pentru **Broker API** (și pentru alocări fără sursă când este configurat un endpoint). Indicatorul animat din bara de stare rămâne vizibil pe durata operației, inclusiv la descărcările manuale. Istoricul CSV nu este înlocuit automat cu Yahoo; se păstrează cu o avertizare pentru reimport/conectare MT5. Dacă o sursă nu răspunde, datele salvate sunt păstrate, celelalte alocări continuă actualizarea și la final apare o avertizare. Tokenurile API nu se salvează: dacă endpointul cere autentificare, introdu tokenul și apasă **Fetch broker data**. Actualizarea la pornire nu schimbă valuta contului și nu generează automat setări EA.
- **Connect MT5: get specs + 5y D1** citește contractul și barele D1 din terminalul MT5 instalat și autentificat. Necesită pachetul oficial Python `MetaTrader5` (`py -m pip install MetaTrader5`); contractul se poate completa și manual.
- **Broker symbol** este o listă populată după **Inspect terminal / symbols** și include simbolurile MT5 inspectate, simbolurile din portofoliu și cache-urile locale. Simbolul implicit este gol, nu `US500`; poți alege orice opțiune din listă. Inspecția creează/actualizează `data/<simbol>/symbol.json` cu metadatele contractului și timeframe-urile disponibile. Datele folosite pentru un simbol se păstrează în `data/<simbol>/market_data.json`; barele charturilor se salvează separat în `data/<simbol>/charts/<TF>.json`.
- **Connect MT5** salvează în `data/<simbol>/charts/<TF>.json` barele pentru timeframe-urile returnate de broker: D1 păstrează fereastra de cinci ani folosită la risc, iar celelalte timeframe-uri maximum 1.000 de bare recente. Refresh-ul automat la pornire preia contractul și D1, fără toate intervalele. Istoricul complet se colectează doar pentru simbolurile alocărilor configurate; alocările duplicate reutilizează același fetch.
- Importul fișierelor MT5 și conectarea prin URL REST nu sunt disponibile în interfață; folosește conectarea MT5 directă sau Yahoo.
- Compatibilitate: URL-urile salvate din versiuni anterioare nu mai sunt încărcate, iar scenariile vechi cu sursa **Broker API** folosesc Yahoo la refresh. Snapshot-urile locale MT5 CSV rămân păstrate; pentru date contractuale lipsă folosește conectarea directă MT5.
- Teste: `py -m unittest -v`.
- Calculatorul în terminal rămâne disponibil prin `py risk_calculator.py`.
- Dacă backup-ul local nu conține cotația, istoricul sau câmpurile obligatorii ale contractului unei alocări, apare un dialog modal cu progres. Când lipsesc datele contractului, plannerul încearcă preluarea directă din terminalul MT5; sursa **MT5 CSV** nu este înlocuită automat. La terminarea cu eroare ecranul se deblochează și avertizarea explică problema; datele salvate existente nu sunt șterse. Blocarea se aplică doar ferestrei plannerului, nu întregului laptop.

În terminal, plafonul lotului este afișat cu precizia Decimal calculată, fără rotunjire suplimentară la patru zecimale. Rotunjește în jos la pasul de volum și verifică volumul minim/maxim al brokerului; terminalul nu importă aceste limite. Pierderea pentru recomandarea selectată este calculată la plafonul lotului, înainte de rotunjirea la pasul brokerului, nu la 1 lot. Modul de căutare cere o mișcare adversă pozitivă; verificarea cu mișcare zero nu determină un plafon de lot, deoarece calculatorul din terminal nu include costurile de execuție.

Step Value și conversia puncte per pip trebuie să fie fiecare strict pozitive, înainte de conversie; două valori negative nu formează un pas valid chiar dacă produsul lor este pozitiv. Configurația propusă în terminal cere și Take Profit Value strict pozitiv, atât în pips, cât și procentual. Valorile valide sunt păstrate, nu optimizate automat.

Motorul de calcul respinge explicit capitalul și limitele de pierdere nefinite (`NaN`, infinit), inclusiv capitalul alocărilor. Numărul maxim de tranzacții, limita candidaților și lungimea minimă a istoricului trebuie să fie întregi strict pozitivi; valorile fracționare sau booleene nu sunt convertite implicit. Aceste verificări se aplică și apelurilor directe ale funcțiilor Python, nu doar formularului.

## Alocări multiple pe același simbol

Poți avea mai multe instanțe cu același simbol, robot și ticker. Selectorul afișează și identificatorul intern al alocării, pentru a păstra fiecare instanță selectabilă separat. Contractul, capitalul și Magic Number-ul atribuit la generare rămân separate. Raportul indică identificatorul, capitalul și bugetul fiecărei alocări; mesajele despre date lipsă identifică instanța afectată.

Scenariile păstrează selecția după poziția alocării în listă, inclusiv pentru instanțe cu nume identice. Identificatorii afișați sunt locali aplicației și se pot schimba după reîncărcare; nu sunt Magic Numbers și nu sunt exportați ca parametri EA. Step, Take Profit și celelalte setări comune ale formularului nu devin preseturi independente per instanță.

Fiecare robot nou se adaugă prin procent din capitalul contului. Capitalul alocat este recalculat din procent când se schimbă capitalul contului; procentele alocărilor noi nu pot depăși împreună 100%. Scenariile mai vechi cu alocări introduse în bani rămân compatibile și își păstrează sumele. Limita procentuală se calculează din capitalul total, apoi plafonul efectiv se distribuie între roboți proporțional cu capitalul alocat. Fiecare candidat folosește maximum 80% din cota lui, astfel încât allowance-urile să nu depășească împreună 80% din limita comună.

La recomandarea agregată, raportul însumează pierderea modelată a tuturor roboților și o compară cu plafonul comun: **ACCEPTED** până la 80%, **NOT ACCEPTED** peste buffer și **REJECTED** când depășește plafonul efectiv. Lipsa datelor, istoricului recent sau limitei totale prop produce **UNVERIFIED**. Raportul complet rămâne vizibil și la verdict neacceptat; copierea/exportul setărilor pentru întregul portofoliu este permisă numai cu verdict **ACCEPTED**. Setările strategice Step, Take Profit și RSI rămân introduse de utilizator și nu sunt optimizate. Rezultatul nu este aprobarea firmei prop sau o garanție de risc live.

## Date de contract și istoric MT5

1. Contractul brokerului (valoarea punctului, point size, volum minim/pas/maxim și valuta valorii punctului) se citește cu **Connect MT5: get specs + 5y D1** dacă terminalul este instalat, autentificat și disponibil prin pachetul Python `MetaTrader5`; câmpurile pot fi completate și manual. Yahoo nu furnizează specificațiile CFD-ului.
2. Conectarea MT5 citește bare D1 pentru simbolul exact al brokerului. Se cer cel puțin 20 de bare zilnice valide, iar datele se salvează în JSON-ul local și se reîmprospătează la conectare.
3. **Suggest all robots (historical drawdown)** reîmprospătează Yahoo pe ultimii cinci ani pentru alocările fără istoric MT5. Un snapshot Yahoo complet se poate folosi offline cu avertizare. Datele Yahoo pot diferi de CFD-ul brokerului; importurile CSV MT5 nu sunt disponibile în interfață.

### Verificarea datelor și conexiunii

În **Portfolio**, **Data status** arată pentru fiecare robot sursa, cotația și momentul ei, prima/ultima zi din istoric, numărul barelor și câmpurile de contract lipsă. Raportul agregat include perioada efectivă și comisionul fiecărei alocări, inclusiv folosirea fallback-ului comun. Un răspuns cu 20 de bare nu mai este prezentat ca istoric complet de cinci ani.

Pentru verdict istoric verificat se cer: prima bară cel târziu la 14 zile după începutul ferestrei de cinci ani, ultima bară cu cel mult 7 zile înainte de data UTC curentă, nicio dată viitoare și minimum 1000 de bare zilnice. Pragurile sunt verificări conservatoare de calitate, nu dovada că toate ședințele sau toate mișcările pieței sunt prezente. Istoricul insuficient poate fi păstrat și inspectat, dar nu produce **ACCEPTED** în modurile istorice. Recomandarea agregată automată solicită rezolvarea avertizărilor înainte de a exporta setări acceptate.

În secțiunea **MT5 connection**, **Choose...** selectează executabilul terminalului; **Automatic** revine la detectarea pachetului MT5. Preferința se salvează local în `data\mt5_connection.json` și este folosită atât la conectarea manuală, cât și la refresh-ul de pornire. **Inspect terminal / symbols** citește în fundal brokerul, serverul, tipul DEMO/CONTEST/REAL, valuta, leverage-ul, marja liberă și lista exactă de simboluri, apoi deschide **Data status**. Această inspecție este informativă și rămâne numai în sesiunea curentă; nu salvează login/parole și nu plasează ordine. Marja liberă afișată nu este încă un calcul de marjă al gridului.

Conectarea MT5 respinge o valută diferită de cea a contului configurat, fără a modifica sumele sau datele existente. Nu există conversie valutară implicită: pentru altă valută, reintrodu explicit capitalul și limitele cash corespunzătoare înainte de reconectare.

La refresh MT5 se păstrează conversia pip și comisionul manual când valorile lipsesc din răspuns și specificațiile numerice ale contractului/valuta nu s-au schimbat. Dacă specificațiile s-au schimbat, valorile vechi nu sunt copiate, apare avertizare și generarea automată este oprită pentru verificare. Specificații egale nu dovedesc că brokerul/serverul este același: scenariile existente nu au proveniență de server, iar comisionul, convenția pip și terminalul activ trebuie reverificate când schimbi brokerul.

Importul respinge rândurile trunchiate, coloanele cu nume duplicate și timestamp-urile duplicate pentru același simbol, în loc să aleagă arbitrar un close sau să numere de două ori eșantioanele de spread. Când coloana `timeframe` este completată, nu amesteca timeframe-uri diferite pentru același simbol în același fișier. Simboluri diferite pot avea același timestamp. Data/ora trebuie exprimată în timpul local al brokerului, fără `Z` sau offset de fus orar; orele invalide nu sunt înlocuite automat cu miezul nopții.

Prețurile Yahoo sunt doar fallback/referință și pot diferi de CFD-ul brokerului. Valoarea punctului, valuta contului, volumul minim și pasul de lot trebuie să corespundă exact contractului MT5. Istoricul MT5 este mai apropiat de instrumentul tranzacționat, dar tot nu prezice prețul sau execuția viitoare.

### Conector REST legacy (nu este disponibil în interfață)

Conectorul și configurarea URL-urilor au fost retrase din interfață. Secțiunea de mai jos descrie formatul folosit de scenarii vechi și nu este o metodă disponibilă pentru configurarea datelor noi; folosește conectarea directă MT5 sau fallback-ul Yahoo.

```json
{
  "account_currency": "USD",
  "symbol": "US500",
  "quote": {
    "price": "5000.25",
    "currency": "USD",
    "time": "2026-10-20T10:00:00Z"
  },
  "contract": {
    "point_size": "0.1",
    "point_value_per_point_per_lot": "1.25",
    "points_per_ea_pip": "10",
    "lot_step": "0.01",
    "min_lot": "0.01",
    "max_lot": "100",
    "commission_per_lot": "2.5",
    "contract_currency": "USD"
  },
  "bars": [
    {
      "date": "2026-10-19",
      "open": "4998",
      "high": "5010",
      "low": "4990",
      "close": "5001",
      "spread_points": "3",
      "spread_sample_count": 100
    }
  ]
}
```

`bars` trebuie să conțină cel puțin 20 de bare zilnice valide, cu date unice, în format `YYYY-MM-DD`; se verifică OHLC, valoarea contractului și potrivirea simbolului/valutei. `contract_currency` trebuie să fie aceeași cu `account_currency`, pentru ca valoarea punctului să fie interpretată corect. Fiecare alocare primește o cerere pentru simbolul ei, iar răspunsurile actualizează cotația, contractul și istoricul brokerului, apoi pornesc estimarea agregată. Datele și tokenul sunt transmise brokerului configurat; folosește doar API-ul oficial al brokerului și verifică permisiunile, unitățile contractului și condițiile de utilizare. URL-ul și tokenul nu trebuie să includă secrete stocate în clar; tokenul se introduce doar în câmpul mascat. Integrarea generică nu implică verificare sau suport oficial pentru un broker anume.

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

### Reguli prop avansate, marjă și swap

În **Prop firm & account → Advanced prop, margin & swap...**, completează și activează explicit verificările avansate. Ele sunt dezactivate la migrarea scenariilor vechi; raportul semnalează că verdictul simplificat nu verifică marja/swap/regulile avansate. Setările sunt salvate împreună cu portofoliul, în scenariul JSON **versiunea 14**, compatibil la încărcare cu versiunile 1–13.

**Account rules:**

- Capitalul contului din formularul principal este capitalul **inițial**, nu equity-ul curent. Introdu separat equity-ul curent și balance/equity de la resetul zilnic.
- Alege explicit baza pragului zilnic: equity, balance sau valoarea mai mare dintre ele. Pragul zilnic este baza minus limita zilnică cash (procentul principal este calculat din capitalul inițial).
- `Static`: prag total = capital inițial minus procentul total din capitalul inițial.
- `Trailing equity`: prag total = high-water equity minus aceeași distanță cash. Este trailing continuu, **fără plafon**, nu trailing de balance sau numai la închiderea zilei. Introdu high-water real; nu poate fi sub capitalul inițial sau equity-ul curent.
- Ora resetului este `HH:MM`, cu offset UTC **fix** în minute; `120` înseamnă UTC+02:00. Nu se presupune automat DST/fusul firmei. Data sesiunii este data locală la care a început intervalul după acest reset. După schimbarea sesiunii, baseline-ul vechi blochează recomandările până când introduci noile valori și data corectă.
- Spațiile zilnic și total rămase sunt calculate separat din equity și praguri. Pentru dimensionarea gridului pe mai multe zile se păstrează intenționat **cel mai mic** spațiu disponibil pe întregul episod; nu se creditează bugete noi la fiecare reset. Sumele „remaining room” introduse în formularul principal pot restrânge suplimentar aceste valori.
- Introdu limita de pierdere pe idee, marja liberă/folosită și stop-out-ul în **procente de margin level**, nu în modul cash. Equity − marja folosită trebuie să coincidă cu marja liberă, cu toleranță 0,02 în valuta contului.

**Per-robot exposure:**

- Folosește aceeași etichetă `Idea group` pentru roboții/corelațiile care trebuie verificate împreună. Capitalul alocat grupului restrânge bugetul înainte de dimensionare, iar pierderile candidate sunt însumate la verificare. Grupele sunt introduse de utilizator; corelația nu este dedusă din prețuri. Verificarea privește roboții planificați, nu descoperă automat alte idei/poziții ale contului.
- `Margin / lot` este o limită superioară conservatoare cash pentru 1 lot; se verifică suma la numărul maxim simultan de intrări. Pierderea stresată plus marja gridului nu trebuie să epuizeze marja liberă, iar margin level stresat trebuie să rămână peste stop-out. Marja poate varia cu prețul și treptele de volum; nu se presupun reduceri pentru hedging/netting. Dacă o configurație depășește marja, este respinsă; nu se prezintă ca recomandare sigură.
- Swap long/short este **debit cash nenegativ în valuta contului / lot / zi de taxare**. Introdu `0` numai dacă este verificat. `Holding days` reprezintă numărul ponderat de zile de taxare, incluzând triple swap/weekend. Rezerva = debit × zile și este adăugată costului **fiecărei intrări încă de la deschidere**, inclusiv în replay; este o estimare conservatoare, nu acumulare calendaristică exactă. Creditele swap nu măresc lotul recomandat. `0` zile înseamnă scenariu fără cost overnight, nu swap gratuit.

Câmpurile obligatorii lipsă produc **UNVERIFIED** sau blochează dimensionarea când costul/bugetul nu poate fi determinat. Depășirile confirmate ale marjei, stop-out-ului ori limitei de grup produc **REJECTED**, inclusiv dacă istoricul este incomplet. Scenariile vechi nu activează automat reguli presupuse.

**Inspect terminal / symbols** citește și equity-ul, marja folosită, modul/pragul de stop-out, estimările `order_calc_margin` BUY/SELL pentru simbolurile portofoliului și swap-urile brute cu modul și ziua triple swap. API-ul doar calculează estimări, nu trimite ordine. Valorile brute swap **nu sunt convertite automat** în cash: pot fi puncte, rate sau altă valută. Verifică unitățile, variația de marjă și condițiile brokerului înainte să introduci limitele normalizate în formular.

În fereastra de stare, selectorul **MT5 symbol for a NEW allocation → Use in Portfolio** completează exact simbolul brokerului în formularul unei alocări noi; alege apoi robotul/procentul și adaugă-l. Nu redenumește alocările existente. Lista brokerului rămâne disponibilă și dacă simbolul introdus anterior nu există sau nu are încă o cotație validă; problemele estimării de marjă sunt afișate separat ca avertizări.

### Verificarea unei curbe de equity MT5 / Strategy Tester

**Evaluate MT5 equity CSV...** verifică o curbă furnizată de utilizator, nu execută robotul și nu transformă lista de tranzacții într-o curbă exactă. Formatul normalizat UTF-8, cu separator virgulă, este:

```csv
timestamp,balance,equity
2026-10-19T00:00:00+02:00,25000,25000
2026-10-19T12:00:00+02:00,25000,24600
2026-10-20T00:00:00+02:00,24600,24600
```

Exportă/loghează aceste valori din testul MT5 ori monitorizarea contului sau normalizează un export care conține efectiv equity. Rapoartele HTML native și listele de deals nu sunt parsate universal. Sunt necesare cel puțin două eșantioane unice, cronologice, cu fus explicit. Limita fișierului este 10 MiB. Confirmă contul/valuta, capitalul inițial și absența depunerilor/retragerilor; pentru trailing, high-water introdus este cel **de la începutul curbei**.

Evaluatorul aplică separat pragul zilnic la resetul configurat și pragul total static/trailing. Lipsa unui eșantion exact la reset sau a unor sesiuni produce **UNVERIFIED**; nu este inventat un baseline verificat din primul eșantion întârziat. O încălcare totală observată rămâne raportată. Egalitatea cu un prag este tratată conservator ca încălcare. Rezultatul este **BREACHED**, **UNVERIFIED** sau **NO SAMPLED BREACH**; ultima etichetă nu înseamnă acceptare prop și nu dovedește că nu au existat pierderi între eșantioane.

Curba, regulile folosite și raportul sunt salvate atomic în `data\equity_validation.json`. **Open saved equity report** îl redeschide offline, etichetat ca snapshot nerecalculat pentru setările de azi. Rezultatul nu aprobă setările candidate ale plannerului, deoarece curba poate proveni din alt preset. Validarea reală necesită rularea EA-ului cu presetul exact în Strategy Tester/demo și colectarea datelor aferente.

Spread-ul din setări este pragul de bază pentru toate alocările. Dacă istoricul MT5 importat are `spread_max_points`, plannerul prioritizează această valoare, agregă maximul zilnic pe simbol și folosește valoarea mai mare dintre spread-ul observat și pragul introdus. Fișierele vechi rămân compatibile prin coloana `spread`. Pentru drawdown peak-to-trough folosește maximul observat în întregul istoric. Spread-ul Yahoo nu este disponibil; fără coloana MT5 rămâne valoarea introdusă manual.

Replay-ul zilnic validează costurile configurate înainte de aplicarea spread-ului istoric: spread-ul, slippage-ul și comisionul trebuie să fie finite și nenegative. Un spread istoric valid nu corectează implicit un spread configurat negativ sau nevalid; apelurile directe ale motorului primesc o eroare explicită.

Prioritatea coloanelor de spread se aplică fiecărui rând: `spread_max_points`, `max_spread_points`, `spread_points`, apoi `spread`. O celulă goală permite folosirea următoarei coloane disponibile; o valoare completată, dar invalidă, oprește importul și nu este ignorată.

`spread_max_points` și `spread_avg_points` sunt calculate din update-urile de tick care conțin Bid/Ask (`COPY_TICKS_INFO`) în intervalul barei. Media este doar informativă și nu intră în calculul recomandării; riscul folosește maximul, nu media. `spread_sample_count` arată câte cotații Bid/Ask valide au fost folosite, iar zero înseamnă că exportul a revenit la valoarea spread-ului barei (`spread`). Numărul de update-uri nu garantează că toate spike-urile au fost observate: lipsa istoricului de tick-uri, limitările brokerului și update-urile dintre bare pot omite valori extreme. Exportul poate dura mai mult deoarece citește tick-urile pentru fiecare bară. Verifică spread-ul și comisionul pentru fiecare CFD; în lipsa unor valori pe simbol, câmpurile comune trebuie setate conservator.

Recomandările limitează `Risk`/lotul inițial la `SYMBOL_VOLUME_MAX` când contractul MT5 importat include `max_lot`. Limita este per ordin și nu reprezintă plafonul volumului total simultan al gridului. Dacă fișierul vechi nu conține această coloană, se poate completa manual sau recomandarea nu are un plafon broker pentru volum maxim. Marja disponibilă și volumul total permis de cont nu sunt încă modelate.

Modul **Historical peak-to-trough drawdown** folosește cel mai mare declin de la un maxim zilnic la minimul ulterior, pe toată perioada importată. Pentru stresul grid, presupune conservator că pozițiile acumulate rămân deschise până la minim și nu creditează închideri Take Profit intermediare. Acesta este modul implicit pentru sugestia agregată, fiind potrivit pentru corecții ample într-o piață bullish. Modul separat **Historical max daily range** păstrează comparația mai puțin severă bazată pe șocuri zilnice independente.

După **Generate candidate settings**, dacă există bare zilnice MT5 și un Take Profit valid, aplicația rulează și o simulare cronologică generică a unei singure campanii de grid: începe la închiderea primei bare, adaugă poziții la pașii configurați, păstrează pozițiile peste zile și închide coșul când prețul atinge TP față de prețul mediu ponderat. Raportează rezultatul net modelat, drawdown-ul equity maxim, pierderea zilnică maximă, numărul maxim de poziții, închiderile TP și dacă prețul a depășit următorul nivel după `Max Trades`. Costurile round-turn configurate sunt scăzute la deschiderea fiecărei poziții; la final, pozițiile rămase sunt evaluate la ultimul close.

Simularea presupune intrări market la atingerea nivelului, nu ordine pending: dacă un gap advers trece de următoarea intrare, aceasta se execută la open, iar următorul nivel este recalculat de la prețul efectiv de intrare. Nu sunt inventate execuții la niveluri sărite de gap. Un gap favorabil care deschide dincolo de TP închide coșul la open, înainte de mișcările ulterioare ale zilei. Spread-ul, slippage-ul și comisionul rămân costuri cash aproximative, nu cotații Bid/Ask simulate.

Această simulare folosește traseul OHLC zilnic presupus „open, mișcarea adversă, cea favorabilă, close” (pentru long: open–low–high–close; pentru short: open–high–low–close). CSV-urile/scenariile vechi fără open rămân compatibile: se folosește close-ul precedent limitat la intervalul low–high al barei, iar raportul avertizează că execuția la gap este aproximată. Reimportă istoricul MT5 pentru a păstra open-ul real. Scenariile noi se salvează în versiunea 14, păstrând open-ul opțional introdus în versiunea 13; încărcarea versiunilor 1–13 rămâne disponibilă.

Drawdown-ul maxim în bani păstrează vârful și minimul episodului respectiv; o recuperare ulterioară nu schimbă aceste date. Drawdown-ul procentual maxim este urmărit separat, fiecare scădere fiind raportată la vârful equity existent atunci, nu la un maxim ulterior. Cele două maxime pot proveni din episoade diferite. Pierderea zilnică folosește equity-ul de la închiderea barei precedente ca bază și include gap-ul și costurile intrărilor; nu implementează ora de reset sau regulile specifice unei firme prop.

Stresul static include și intrarea care se deschide exact la capătul mișcării adverse: pierderea ei de preț este zero în acel punct, dar costurile nu sunt zero. Și barele fără mișcare pot contribui la stres prin costurile de tranzacționare. Din acest motiv, numărul candidat de intrări sau lotul recomandat pot diferi de versiunile anterioare.

Calculul stresului static acumulează pierderile într-o singură parcurgere a intrărilor atinse, fără recalcularea fiecărui prefix al gridului. Aceasta reduce timpul pentru griduri mari fără schimbarea formulei, costurilor sau regulii de 80%. Numărul maxim de tranzacții încadrate în buget reprezintă capacitatea configurabilă în scenariul testat, nu numărul de poziții efectiv deschise: intrările dincolo de mișcarea testată nu adaugă pierdere.

Barele intraday sunt în prezent agregate pe zi înainte de simulare; deci nu este încă replay M1/M5 și nu poate stabili ordinea reală a mișcărilor în interiorul zilei. După atingerea TP, campania rămâne inactivă pentru restul istoricului; nu sunt generate cicluri noi, deoarece semnalele și condițiile reale ale EA-ului sunt necunoscute. Replay-ul nu modelează lichidarea dinamică pe marjă sau acumularea calendaristică exactă a swap-ului; verificările avansate adaugă separat filtrul de marjă la expunere maximă și rezerva swap preplătită descrise mai sus. Nu reproduce execuția reală sau semnalele RSI și nu este echivalent cu Strategy Tester.

Nici simularea, nici modurile de stres nu reproduc complet EA-ul: plannerul nu cunoaște regulile efective de intrare RSI, pozițiile deja deschise, spread-ul din fiecare tick, swap-ul, execuția, gap-urile viitoare sau dacă EA-ul respectă setările recomandate. Pentru RSI, riscul este aproximat ca un grid de poziții la distanțele și multiplicatorul introduse, nu ca o simulare a semnalelor RSI. Fără sursele EA-urilor nu se poate confirma compatibilitatea parametrilor `.set` sau preveni redeschiderea pozițiilor de către robot. Validează scenariile în Strategy Tester și pe demo înainte de folosire.

Recomandarea folosește volume fixe, multiplicator 1.0 și maximum 80% din bugetul de risc configurat. În modul peak-to-trough, aceeași limită de risc este aplicată întregului episod, fără a presupune că pierderea permisă se resetează zilnic — o presupunere deliberat conservatoare. Valorile Step, Take Profit și pragurile RSI rămân decizii de strategie și trebuie backtestate separat. Alocările din raportul agregat sunt presupuse a suferi simultan șocurile lor istorice cele mai nefavorabile.

Toate modurile de generare, inclusiv **Target price** și **Adverse move (%)**, cer valuta contului și valoarea punctului în aceeași valută. Aplicația nu convertește automat valoarea punctului; un contract cu valută lipsă sau diferită trebuie corectat înainte de generare. Raportul agregat respectă plafonul `max_lot` și pasul de volum inclusiv în modurile manuale.

Numărul **Max Trades candidates** limitează acum și căutarea automată istorică, pentru alocarea selectată și pentru raportul agregat. Pentru long, procentul advers trebuie să fie pozitiv și sub 100%, iar prețul țintă trebuie să fie pozitiv. Pentru short, o creștere adversă poate fi de 100% sau mai mare; această valoare este acceptată atât manual, cât și din istoricul disponibil. După o generare eșuată, rezultatul anterior este șters pentru a nu fi confundat cu o recomandare recalculată.

## Export `.set`

**Export .set template** produce un fișier candidate după generarea setărilor. Numele input-urilor și ordinea enum-urilor sunt deduse din lista de parametri furnizată; sursele EA-urilor și un preset real nu sunt în repository pentru a verifica identificatorii efectivi. Verifică fiecare câmp în fereastra Inputs a EA-ului înainte de încărcare și nu folosi presetul direct pe cont live. Exportul nu demonstrează compatibilitatea cu un EA necunoscut.

Blocul de setări candidate afișează parametrii comuni și numai opțiunile specifice DCA sau RSI. DCA păstrează `Show Invested Money=true`; RSI folosește valoarea booleană selectată. Recomandarea automată folosește `Risk Type=Fixed lots`; dacă lotul recomandat este exact volumul minim al brokerului, exportă `Risk=0.0` conform convenției furnizate (EA-ul folosește volumul minim). Template-ul acceptă `Fixed lots` și `Cash`, dar nu `Balance percent`; plannerul nu calculează automat valoarea numerică pentru modul Cash. Ordinalele enum-urilor și identificatorii rămân candidate și trebuie verificați în EA.

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
