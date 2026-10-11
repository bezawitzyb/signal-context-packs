# Demo agent: three TikTok scripts, with and without a Context Pack

Task given to both: *Write three TikTok scripts for a new snack brand launching in the Netherlands. The audience is Dutch snackers aged 18-40.*

- Model: `claude-sonnet-5-5` (reasoner role), same system prompt for both versions.
- With pack: the skill of pack `pk_3I8-9eTZflyz` (Launching a snack brand in the Netherlands): SKILL.md body up front, reference files on demand. Opened: lexicon.md, hooks.md, objections.md.
- Without pack: only the task.
- Generated 2026-10-11 by `backend/scripts/demo_agent.py`. Checks are code, not a model; the pack's lexicon and guardrails are the yardstick for both versions.

## Automatic checks

| Check | Without pack | With pack |
|---|---|---|
| >= 3 lexicon terms | ✗ fail: 0: none | ✓ pass: 8: snacktip, tussendoortjes, lekker, roze koeken, snoep, snack haul, plopkoeken, stropfwaffel |
| 0 not_this / never_claim phrases | ✓ pass: none | ✓ pass: none |
| facts only from safe_to_assert items | ✓ pass: 0 audience fact(s) | ✗ fail: 4 audience fact(s); not safe: THM-05: People tell us a nice pack and a new flavour make them want ; PAIN-02: People tell us protein bars often let them down.; OBJ-04: People tell us they look at sugar and ingredients, also in p; THM-08: People tell us Dutch snacks from childhood still mean someth; 3 brand claim(s) to verify before use: We are a new snack brand launching in the Netherlands and ar; We answer any question about what is in our snack.; This video is an advertisement (reclame / #ad) for our new s |
| cited ids exist | ✗ fail: no ids cited | ✓ pass: 16 cited |
| no copied quotes | ✓ pass: none | ✓ pass: none |

## Script 1

| | Without pack | With pack |
|---|---|---|
| Title | POV: de 15-uur-hap | YAY of NAY: kies jouw crunch |
| Hook | Het is 15:00 uur en je hoofd roept maar één ding: snack. | YAY of NAY: een lekkere, knapperige snack, welke smaak mag het worden? |
| Beats | 1. Beeld: kantoor of studeerkamer, persoon staart naar scherm, maag rommelt hoorbaar. Voice-over: 'Het is 15:00 uur en je hoofd roept maar één ding: snack.'<br>2. Persoon opent de la, ziet alleen een oude rijstwafel. Dramatische zucht. 'Nee. Vandaag niet.'<br>3. Snelle cut: persoon pakt de nieuwe snack uit een tas en opent hem met een knisper-geluid (ASMR, close-up).<br>4. Reactie: ogen groot, knikt langzaam. 'Oké... dit is dus waar ik op wachtte.'<br>5. Eindshot: verpakking in beeld. 'Binnenkort in Nederland. Welke snack redt jouw middag?' | 1. Op tafel staan 3 bakjes met onze nieuwe snack, elk een andere smaak of crunch. Jij filmt close-up en laat het krokant geluid horen.<br>2. Je proeft ze een voor een en zegt eerlijk wat je ervan vindt: smaak eerst, dan crunch. Lekker blijft het hoofddoel.<br>3. Je laat de verpakking zien: 'Wat erin zit staat gewoon op de voorkant, kijk zelf even mee.'<br>4. Vraag: 'Welke smaak is jouw YAY en welke jouw NAY? Zeg het in de comments, dan nemen we het mee.' |
| On screen | 15:00 = snackalarm / De la: leeg / Nieuw in Nederland / Welke snack redt jouw middag? | YAY of NAY? 👀 / Smaak 1 / 2 / 3 / Jij beslist 🗳️ / Nieuw: wij zijn nog aan het testen! |
| Hashtags | #snack #snacktime #nederland #foodtok #nieuwesnack | #YAYofNAY #nieuweproductentesten #snacktip #tussendoortjes #lekker #tastetest |
| Caption | Iedereen kent dit moment. Vertel in de comments wat jouw 15-uur-snack is 👇 | Nieuwe snack, 3 opties, jij bepaalt! 🎉 Welke smaak is jouw YAY en welke jouw NAY? Laat het weten in de comments 👇 Eerlijke mening graag, ook de kritische! |
| Cites | - | PHR-03, PHR-01, LEX-03, HOOK-04, THM-05 |

## Script 2

| | Without pack | With pack |
|---|---|---|
| Title | Blind proeven met vrienden | Eiwitrepen stellen vaak teleur... wat moet een snack kunnen? |
| Hook | Wij laten onze vrienden blind onze nieuwe snack proeven. Eerlijke reacties, geen filter. | Eerlijk: wat vind jij het belangrijkste bij een eiwitsnack? Smaak, crunch, of iets anders? |
| Beats | 1. Beeld: drie vrienden met blinddoek aan tafel. Voice-over: 'Eerlijke reacties, geen filter.'<br>2. Elke vriend krijgt een hapje. Close-ups van gezichten, knisper-geluid, ze raden wat het is.<br>3. Ze mogen een cijfer geven op een whiteboard. Ze lachen en discussiëren over de smaak.<br>4. Blinddoeken af: ze zien de verpakking. 'Wacht, WAT? Dit is nieuw?'<br>5. Call to action: 'Wil jij ook proeven? Volg ons, dan hoor je het als het kan.' | 1. Je zit in beeld met een rij snacks uit de supermarkt, geen merknamen in beeld, en zegt: 'We horen vaak dat eiwitrepen tegenvallen. En dat je het etiket moet checken.'<br>2. Je pakt een etiket en wijst naar suiker en ingrediënten: 'Mensen vertellen ons dat ze letten op suiker en wat er precies in zit, ook bij dingen die gezond heten. Terecht!'<br>3. Je zegt: 'Wij zijn nieuw, dus je mag alles vragen: wat erin zit, welke eiwitbron, hoeveel suiker. We antwoorden gewoon.'<br>4. Vraag: 'Wat is jouw ultieme snacktip? En wat moet een nieuwe snack écht goed doen voordat je hem koopt?' |
| On screen | Blind proeven 👀 / Eerlijke reacties / Jouw cijfer? / Volg voor de launch | Wat is jouw ultieme snacktip? 💬 / Check het etiket 🔍 / Vraag maar raak ❓ / Smaak, crunch, prijs? |
| Hashtags | #blindtest #proeven #snacks #foodtok #nederland | #snacktip #eiwitsnack #etiketcheck #nieuweproductentesten #tussendoortjes #foodie |
| Caption | Wat zou jij als eerste raden? Laat het weten 👇 | Wij zijn nieuw en luisteren eerst 👂 Wat moet een snack doen voordat jij hem in je mandje gooit? Smaak, crunch, ingrediënten, prijs? Zet je snacktip in de comments! 👇 |
| Cites | - | PAIN-02, OBJ-03, OBJ-04, LEX-01, PHR-01 |

## Script 3

| | Without pack | With pack |
|---|---|---|
| Title | Snack-dilemma: jij beslist | Snack haul: er mag alles in |
| Hook | Zoet of hartig? Kies nu, er is geen neutrale optie. | Snack haul! Snoep, koek én iets nieuws, en niemand oordeelt. |
| Beats | 1. Beeld: split screen, links een zoete snack-silhouet, rechts een hartige. Voice-over: 'Zoet of hartig? Kies nu.'<br>2. Snelle lijst van mini-dilemma's als tekst-overlays: 'Bank of bureau? Filmavond of feestje? Alleen opeten of delen?'<br>3. Gezicht in beeld: 'Wij bouwen een snackmerk voor Nederland en willen weten wat jij écht wilt.'<br>4. 'Reageer met jouw keuze en jouw perfecte snackmoment. We lezen alles.' | 1. Je pakt een tas uit op de bank: chips, snoep, een stropfwaffel, roze koeken en onze nieuwe snack ertussen.<br>2. Je zegt per product één woord, vooral waar je blij van wordt. Je zegt erbij: 'Hier wordt niks fout gevonden, er mag alles in.'<br>3. Je proeft onze nieuwe snack naast een favoriet en geeft een eerlijk oordeel, ook wat jij minder vindt. Reclame / #ad staat in beeld.<br>4. Vraag: 'Welke snack uit je jeugd mis jij nog? Plopkoeken, roze koeken, stropfwaffel? Zeg het in de comments 🥹' |
| On screen | Zoet 🆚 Hartig / Alleen opeten of delen? / Jij bepaalt mee / Reageer hieronder | Snack haul 🛍️ / Er mag alles in! / Reclame / #ad / Welke snack mis jij nog? 🥹 |
| Hashtags | #zoetofhartig #snackers #nederland #foodtok #nieuwmerk | #snackhaul #roze koeken #stropfwaffel #plopkoeken #snacktip #reclame |
| Caption | Wij lezen elke reactie. Zoet of hartig, en wanneer snack jij? 👇 | Snack haul met alles erin: snoep, koek en iets nieuws 🍬🍪 Welke snack uit je jeugd mis jij nog? Vertel! 👇 Reclame, eerlijke mening inbegrepen. |
| Cites | - | THM-08, LEX-04, LEX-06, LEX-07, LEX-10, HOOK-06, HOOK-07 |

Scripts are generated examples, not tested ads. Facts the pack does not mark safe to state need checking first; see the pack's guardrails and compliance flags.
