# WAM on WhatsApp — guide for doctors and the front desk

Message the clinic's WhatsApp number from **your own phone** (the number saved for you in WAM admin). WAM
knows it's you. Anything that cancels visits or messages many patients asks you to reply **YES and your PIN**.

| Send | What happens | PIN? |
| --- | --- | --- |
| `Today's list` | Today's appointments, numbered (doctors see their own) | No |
| `Tomorrow's list` | Tomorrow's appointments | No |
| `Cancel my 5 pm` | Cancels that visit; the patient gets 3 new slots and is rebooked when they reply | **Yes** |
| `Cancel Dr Mehta 5 pm` / `Cancel Rahul tomorrow` | Same, for another doctor or by patient name | **Yes** |
| `Running 20 min late` | Tells your next patients (next 4 hours) | No |
| `On leave Friday` / `On leave 12 Oct to 14 Oct` | Blocks the days and moves everyone booked | **Yes** |
| `Rahul, root canal` | Enrols Rahul in the plan; if a visit is due now he gets 3 free slots | No |
| `Karan 98xxxxxxxx, laser` | Same for a new patient (include the number) | No |
| `Rahul, root canal, 1 done` | Enrol when the first sitting is already done | No |
| `Aarav 98xxxxxxxx, vaccination, born 12/03/2026` | Child reached through the parent's number | No |
| `Follow-up for Rahul in 7 days` | WAM messages Rahul with free slots in 7 days | No |
| `Find Rahul` | Rahul's plans and upcoming visits | No |
| `Summary` | Today's numbers: visits, new bookings, cancellations, chats waiting | No |
| `help` | This list | No |

**Confirming:** reply `YES 1234` (your PIN) within 10 minutes, or `NO`. Five wrong PINs lock confirmations
for 15 minutes; the owner can reset your PIN in WAM admin.

## End-of-day check (30 seconds)

At closing time the front desk gets today's list. Reply with the **numbers of anyone who didn't come**, for
example `2 5`. Everyone else is marked as came. If everyone came, reply `none`. Made a mistake? Send the
corrected numbers again — WAM fixes it. If the message says "Reply LIST", send `list` first.

WAM follows up with patients who missed a visit after 24 hours with new slots, tries once more, and then
asks you to call them.

## When WAM hands a chat to you

WAM hands the chat to the team in the WAM inbox when a patient asks for a person, asks a medical question,
complains, sends a voice note, or uses emergency words (then you also get a WhatsApp alert). Reply from the
inbox; WAM stays quiet while a person is assigned to the chat. Resolve the chat when you're done and WAM
takes over again.
