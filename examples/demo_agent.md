# Demo agent: three TikTok scripts, with and without a Context Pack

Task given to both: *Write three TikTok scripts for a new snack brand launching in the Netherlands. The audience is Dutch snackers aged 18-40.*

- Model: `claude-sonnet-5-5` (reasoner role), same system prompt for both versions.
- With pack: the skill of pack `pk_wrvZBhDFsLR9` (Launching a snack brand in the Netherlands): SKILL.md body up front, reference files on demand. Opened: lexicon.md, hooks.md, evidence.json, tensions.md, objections.md.
- Without pack: only the task.
- Generated 2026-10-05 by `backend/scripts/demo_agent.py`. Checks are code, not a model; the pack's lexicon and guardrails are the yardstick for both versions.

## Automatic checks

| Check | Without pack | With pack |
|---|---|---|
| >= 3 lexicon terms | ✗ fail: 0: none (not counted, also under never_claim: verslavend lekker) | ✗ fail: 1: jeugdsentiment (not counted, also under never_claim: verslavend lekker) |
| 0 not_this / never_claim phrases | ✓ pass: none | ✓ pass: none |
| facts only from safe_to_assert items | ✗ fail: 1 audience fact(s); not safe: no id: Nederlanders zijn niet bang om hun mening te geven.; 2 brand claim(s) to verify before use: Het merk komt binnenkort naar Nederland.; Wij lanceren een snack in Nederland. | ✗ fail: 2 audience fact(s); not safe: no id: Kcal, suiker en de ingrediëntenlijst staan op het etiket van |
| cited ids exist | ✗ fail: no ids cited | ✓ pass: 14 cited |
| no copied quotes | ✓ pass: none | ✓ pass: none |

## Script 1

| | Without pack | With pack |
|---|---|---|
| Title | POV: het 22:00-snackmoment | Zak omdraaien: kcal en suiker hardop |
| Hook | Het is tien uur 's avonds en je staat al voor de kast. Again. | Ik draai de zak om en lees kcal en suiker per portie hardop voor. Wie kijkt er mee? 🙈 |
| Beats | 1. Beeld: persoon in joggingbroek opent keukenkastje, kijkt naar saaie opties. Zucht.<br>2. Voice-over: 'Chips? Te voorspelbaar. Komkommer? Dat is geen snack, dat is een straf.'<br>3. Persoon pakt de telefoon: 'Er moet gewoon iets nieuws komen.'<br>4. Cut naar een zwarte scherm-teaser met het merklogo: 'Binnenkort in Nederland.'<br>5. Voice-over: 'Jij bent onze eerste proefpersoon. Volg ons, dan weet je het als eerste.' | 1. Close-up: drie zakken snacks naast elkaar op tafel, je pakt ze één voor één op en draait ze om. Snel tempo, geen opgeklopte reclametoon.<br>2. Per zak lees je hardop voor wat er op het etiket staat: kcal per portie, suiker per portie en de eerste ingrediënten. De cijfers komen letterlijk van de zak en staan in beeld.<br>3. Geen oordeel over merken, alleen: 'Dit staat erop. Jij mag zelf beslissen.' Waar een portie klein is, zeg je dat ook eerlijk, bijvoorbeeld als je de hele zak opeet.<br>4. Sluit af met de camera op de drie zakken: 'Welke zak moet ik hierna checken? Zet hem in de comments.' |
| On screen | POV: 22:00, kastje open / Chips = te voorspelbaar / Er komt iets nieuws / Binnenkort in NL 🇳🇱 | Zak om. Cijfers erbij. / kcal + suiker per portie / Ingrediëntenlijst hardop / Welke zak moet ik hierna checken? |
| Hashtags | #snacks #nederland #snacktime #foodtok #nieuwmerk | #snacktip #labelcheck #supermarkt #snacks #kcal |
| Caption | Wie staat er ook elke avond voor die kast? 👀 Er komt iets nieuws aan. | Zak om, cijfers hardop. Geen oordeel, gewoon wat er op het etiket staat 🙈 Welke zak moet ik hierna checken? |
| Cites | - | THM-02, OBJ-01, TEN-01, MOT-04 |

## Script 2

| | Without pack | With pack |
|---|---|---|
| Title | Snack-confessions: wat is jouw guilty pleasure? | Oh wat mis ik die: jeugdsentiment-lijst |
| Hook | Zeg eerlijk: wat eet jij als niemand kijkt? | Oh wat mis ik die! Welke snack uit je jeugd zie je niet meer in de schappen? Zet je jeugdsentiment in de comments, ik maak er een lijst van. |
| Beats | 1. Beeld: snel gesneden shots, maker met een 'biecht'-stoeltje en een lege tafel.<br>2. Maker biecht zelf als eerste: 'Ik eet dingen uit de zak, staand in de keuken. Geen bord. Nooit.'<br>3. Maker: 'Dat is geen schande, dat is gewoon snacken.'<br>4. Maker wijst naar de comments: 'Biecht jij het hieronder? Beste antwoord gaat mee in onze launch-video.'<br>5. Eindshot: logo en 'Wij luisteren. Echt.' | 1. Je staat in een supermarktgangpad en kijkt naar een leeg stuk schap. Je zegt grappig-teleurgesteld: 'Hier lag vroeger iets.'<br>2. Je laat je eigen jeugdsentiment zien: paprikachips op het kinderfeestje (kinderfeestje flashback), een zak chips met een bakje knoflooksaus ernaast, en het gehaktbalbroodje bij de supermarktbakker. Alles als jouw eigen herinnering, niet als feit over waarom het weg is.<br>3. Je zegt: 'Soms vind je in je eigen supermarkt gewoon niet wat je zoekt. En ik zie mensen vaak vragen waarom een favoriet weg is, terwijl niemand dat uitlegt.'<br>4. Afsluiter: 'Ik pitch niks. Ik lees alles en reageer op iedereen. Welke snack uit je jeugd mis jij het meest, en waarom?' |
| On screen | Snack-biecht 🙊 / Staand in de keuken = klassiek / Jouw confession ⬇️ / Beste antwoord in onze launch-video | Oh wat mis ik die! 🥹 / Jouw jeugdsentiment, in de comments / Ik maak er een lijst van / Welke snack mis jij? |
| Hashtags | #snackconfession #guiltypleasure #nederlandsesnacks #foodtok #fyp | #jeugdsentiment #flashback #snacks #nostalgie #ohwatmisikdie |
| Caption | Jouw snack-geheim is bij ons veilig. Zet het in de comments 👇 | Welke snack uit je jeugd mis jij nog? Vertel waarom, ik reageer op iedereen en maak een lijst 🥹 |
| Cites | - | MOT-01, THM-01, WSP-02, EV-0036, EV-0056, EV-0064 |

## Script 3

| | Without pack | With pack |
|---|---|---|
| Title | Wij zoeken 100 snackers die eerlijk zijn | Chipsduel: paprika vs Nacho Cheese |
| Hook | Wij zijn nieuw, en we willen dat jij ons afkraakt. | Paprika of Nacho Cheese? Noem je favoriete chipsmaak, dan leg ik ze naast elkaar op smaak, crunch en kcal. Ik hou van chips! |
| Beats | 1. Beeld: maker in close-up, direct in de camera, droog toontje.<br>2. Maker: 'We lanceren een snack in Nederland. En Nederlanders zijn niet bang om hun mening te geven.'<br>3. Maker: 'Dus we doen dit anders: jij zegt wat je écht wilt in een snack. Zout, zoet, krokant, ruim zakje. Alles mag.'<br>4. Tekst verschijnt in beeld terwijl maker de comments laat zien: 'Wat moet erin, wat moet eruit?'<br>5. Maker: 'Volg ons als je mee wilt denken. Eerlijk is prima.' | 1. Split screen: links een zak paprika, rechts een zak Nacho Cheese. Jij tussen de twee zakken met een serieuze scheidsrechterblik 😂.<br>2. Ronde 1, smaak: één chip van elk, eerlijke reactie in één zin. Ronde 2, crunch: je houdt de chip bij de camera zodat je het hoort breken.<br>3. Ronde 3, kcal: je draait beide zakken om en leest kcal per portie van het etiket hardop voor. Het getal staat in beeld, zonder oordeel.<br>4. Noem ook de uitdagers die je volgende week wilt testen: Thai Sweet Chili en Cool America. Vraag: 'Wat is jouw nummer één? Dan komt die in de volgende ronde.' |
| On screen | Nieuw in NL / Kraak ons af 😅 / Wat moet er in je snack? / Volg voor de launch | Paprika vs Nacho Cheese / Smaak / Crunch / kcal / Volgende ronde: Thai Sweet Chili, Cool America / Jouw favoriet? Comments 👇 |
| Hashtags | #snacks #feedback #nederland #startup #foodtok | #chips #paprika #nachocheese #snacktest #ikhouvanchips |
| Caption | Nieuw merk, eerlijke feedback gezocht. Wat wil jij in je perfecte snack? 👇 | Paprika of Nacho Cheese? Smaak, crunch en kcal naast elkaar. Zet jouw favoriete smaak in de comments, dan testen we die ook 🧀🌶️ |
| Cites | - | MOT-05, EV-0055, EV-0009, EV-0088 |

Scripts are generated examples, not tested ads. Facts the pack does not mark safe to state need checking first; see the pack's guardrails and compliance flags.
