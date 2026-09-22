# Sample prompts

Things to say to an assistant that has this skill. Each one exercises a
different chapter — reading, adding, cards.

## Getting oriented

> What keepr collections can you see?

> What does my Reading log collection accept? Show me the fields and their types.

> What fields does the Expense card have, and which ones are required?

## Reading

> What's in my Reading log? Just the ten most recent.

> How many books did I finish this year? Which had five stars?

> How much did I spend at Blue Bottle in the last 90 days? List the receipts.

> Which residents moved in before 2024 and have no room assigned?

> Find the contact at Northwind — I think the name was Leah something.

> Is there anything in keepr mentioning "scissors"?

> Show me the work orders for Truck 14 that are still open, with a link to each.

## One record at a time

> Log in keepr that I finished Piranesi today — five stars.

> Add an expense to my Expenses collection: $18.50 at Blue Bottle Coffee on
> March 14th, meals, reimbursable, receipt BB-4471.

> Here's a photo of a receipt. Add it to Expenses and attach the photo to the record.

## Several at once

> Here are my notes from this week's calls. Create a contact for each person
> and a note for each conversation, linked to the right contact.
>
> Tue — Leah Park (Northwind, leah@example.com): wants Q4 numbers before the 20th.
> Thu — Sam Ortiz (Northwind, sam@example.com): prefers a written summary over a call.

> Import `books.csv` into my Reading log. The ISBN column is the unique id.

> Take the table at the bottom of this PDF and add each row to my Inventory
> collection. Show me what you're going to write before you write it.

## Re-running and fixing

> I fixed three rows in books.csv — sync it again without creating duplicates.

> Four rows failed last time. What went wrong, and can you fix them?

> What did you put into my Expenses collection yesterday?

## Setting up from scratch

> I want to track my houseplants in keepr — species, where it lives, how often
> to water, last watered, a photo. Set up the card and add these six plants.

## Changing a card

> Add an ISBN field to my Book card.

> Rename the "Notes" field on my Contact card to "Background".

> Change the rating on Book from a 5-star scale to a 10-point one.

> Add a "publisher" field to Book, then fill it in for the ones in this list.

> Remove the "shelf" field from Book — I don't use it. *(The assistant will
> tell you how many books have a shelf recorded, and ask you to confirm by the
> card's name before anything is lost.)*

## Sample data in this folder

| file | try it with |
| --- | --- |
| `books.csv` | "Import books.csv into a new Reading log card." |
| `expenses.json` | "Dry-run this rows file against my Expenses collection." |
| `contacts-and-notes.json` | "Load these contacts and notes, keeping the links." |

Each sample carries `source.externalId` on every row, so you can import it,
change a value, and import again to watch `updated` and `skipped` do their job.
