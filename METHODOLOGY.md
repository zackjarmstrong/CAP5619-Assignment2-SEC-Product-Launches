# Finding New Product Launches in SEC Form 8-K Filings
CAP5619 - Artificial Intelligence and Finance | Assignment 2 | November 2026

## Purpose and data

For this assignment, I used Python and a large language model (LLM) to find announcements of new products in SEC Form 8-K filings. My goal was to produce a CSV containing the company name, ticker symbol, filing time, product name, and a description shorter than 180 characters. I included newly launched services and investment offerings when the filing described them as distinct, available products.

I searched SEC filings for phrases such as “announced the launch,” “today launched,” and “now available.” The search produced 1,417 unique filing URLs spanning 2020 through October 2026. I then used Python requests and BeautifulSoup to retrieve the filings and their attached press releases (often EX-99 exhibits), remove HTML formatting, and extract the text. A preliminary screening step helped prioritize filings that looked like actual product announcements rather than routine financial updates.

## LLM extraction

I used the OpenAI Responses API with the gpt-6-luna model. This was an inference task: I did not train or fine-tune a model. For each selected filing, I passed the relevant text to the model and asked it to identify the company and any newly launched products, describe each product concisely, and provide supporting language from the source. In this way, the model performed the entity-recognition portion of the task, identifying company names as organizations and product names as products.

The Python code required structured JSON output, checked field types and description lengths, and used SEC filing metadata for timestamps instead of relying on the model to generate dates. I also compared the model’s supporting quotes with the filing text and checked for repeated products. Some filings announced several distinct products, so a single document could produce more than one CSV row.

## Checking results and handling problems

The hardest part was deciding whether a filing described a genuinely new launch. Searches frequently returned earnings reports that mentioned older products, future development plans, beta releases, or rebranding announcements. I excluded those when the evidence did not support a current launch. I also kept uncertain cases out of the final CSV instead of treating the model’s confidence score as proof.

Another issue was inconsistent formatting in SEC documents. HTML extraction sometimes inserted spaces or changed punctuation in quoted text, and some model responses needed corrections to meet the description limit. The project keeps the original source URLs and an evidence log so the decisions can be reviewed. One ticker, Genius/VERSES AI, had conflicting historical symbols in SEC exhibits; I retained the SEC-derived value, VRSSD, and documented the uncertainty rather than guessing.

## Results and limitations

The final CSV contains **100 products from 62 companies**. The saved analysis history covers **187 distinct filings analyzed with an LLM**, while a larger set was screened without an LLM call. The extraction workflow used 153 new API requests. The final dataset has the five required columns, no duplicate product entries, and descriptions of no more than 169 characters. Nine uncertain candidates and 26 rejected candidates were excluded.

These results should be viewed as a selected sample, not a complete list of every product released by public companies. Some launches may have been missed, and the presence of a product in a company press release does not independently verify its performance. Source checks were AI-assisted, so I do not claim that every product was independently verified by a person.

## AI assistance and references

I used ChatGPT/Codex to help develop and test the Python workflow, review extracted entries against SEC source documents, and draft and revise this report. I reviewed the assignment requirements and made the final decisions about the project scope and submission. The Python code, final CSV, SEC evidence references, and usage documentation are available in the public GitHub repository below.

**GitHub:** https://github.com/zackjarmstrong/CAP5619-Assignment2-SEC-Product-Launches

