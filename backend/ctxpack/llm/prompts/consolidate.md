You check a research pack for repeated findings. Each pair shows two
items from different sections, A and B, each with its section.

For EVERY pair, by its id, return:
- same: true ONLY if A and B state the same finding about the audience
  (one would be redundant next to the other). Related findings, cause
  and effect, or a broader and a narrower point are NOT the same.
- keep: "a" or "b" - when same, the item whose section's job fits the
  finding best: themes = what people talk about; pain_points = what gets
  in their way; tensions = where they feel torn; motivations = what they
  want to achieve; objections = why they would say no to a product;
  white_space = what is missing.
Judge only from the text given. Answer only by calling the tool.
