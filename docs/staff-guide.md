# WAM on WhatsApp — guide for staff

Clinics: see the commands below. Institutes: see [Institutes](#institutes) further down.

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

## Institutes

Coordinators, teachers and the front desk message the **institute's** WhatsApp number from their own phones,
so no teacher's personal number becomes the helpline. Anything that messages many people asks for **YES and
your PIN** first.

| Send | What happens | PIN? |
| --- | --- | --- |
| `Send to NEET-A2: Tomorrow's class is at 4 PM` | Shows a preview and the number of people, then sends to every student and parent in the batch, each individually | **Yes** |
| `Send to NEET-A2 parents: PTM on Saturday` | Same, parents only (or `students`) | **Yes** |
| `Absent NEET-A2 Physics: 12, 15, 21` | Parents of those students (roll numbers or names) get an absence alert | **Yes** |
| `Announcement status` | Sent, delivered and read counts of your last announcement | No |
| `Aarav paid` / `Paid 12` | Records the next fee installment and tells you when the next one is due | No |
| `Aarav, fees` | Puts Aarav on the fee installment plan | No |
| `My batches` | Your batches and how many students each has | No |
| `Today's list`, `Summary`, `Find Aarav`, `help` | As above | No |

**Who can do what:** coordinators can message any batch; teachers only the batches they are linked to in
WAM admin (Batches → a batch → Teachers). The owner sets roles under Setup → Staff & roles.

**Doubts:** when a student sends `Doubt: …`, WAM works out the subject (or asks) and assigns the chat to that
subject's team in the WAM inbox. Reply from the inbox; resolving the chat closes the doubt.

**Parent-teacher meetings:** create the meeting in WAM admin (Parent-teacher meetings). Parents reply `PTM`
and pick a slot; the bookings show in Today's list and Appointments.

**Sheets:** attendance, test results, student lists and the timetable are uploaded in WAM admin → Uploads.
You always see a preview (who matched, which rows have problems, how many messages) before anything is sent.
