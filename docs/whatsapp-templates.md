# WhatsApp message templates

WAM can reply freely only within 24 hours of a patient's (or staff member's) last message. Anything WAM
starts outside that window goes out as one of these Meta-approved templates. Inside the window WAM sends a
richer free-text version of the same message instead.

**Submit all clinic templates in week 2** (Meta Business Manager → WhatsApp Manager → Message templates):

- Use the **exact name** below (WAM looks templates up by name and language).
- Category: **Utility**. Language: the code you set in WAM admin → Setup → Clinic → *Template language code*
  (default `en`).
- Paste the body exactly; add the example values when Meta asks for samples.
- Meta rules followed here: no variable at the start or end of the body, no two variables side by side.

This file is generated from `core/wam/templates.py` (the source of truth). The same list is shown in
WAM admin → WhatsApp templates.

## `wam_session_due`

Pack: clinic · Category: UTILITY · Language: en

```
Hi {{1}}, your {{2}} with {{3}} is due. Free slots: {{4}}. Reply 1, 2 or 3 to book, or tell us a time that suits you.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | name | Rahul |
| `{{2}}` | session | Root canal (2nd sitting) |
| `{{3}}` | resource | Dr. Mehta |
| `{{4}}` | slots | 1) Mon 12 Oct, 10:00 AM 2) Tue 13 Oct, 5:30 PM |

## `wam_day_before_reminder`

Pack: all · Category: UTILITY · Language: en

```
Reminder: {{1}} with {{2}} tomorrow at {{3}}. Reply 1 to confirm or 2 to reschedule.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | service | Root canal (visit 2 of 3) |
| `{{2}}` | resource | Dr. Mehta |
| `{{3}}` | time | 5:30 PM |

## `wam_missed_followup`

Pack: clinic · Category: UTILITY · Language: en

```
Hi {{1}}, we missed you at your last visit. Next free slots: {{2}}. Reply 1, 2 or 3 to book.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | name | Rahul |
| `{{2}}` | slots | 1) Mon 12 Oct, 10:00 AM 2) Tue 13 Oct, 5:30 PM |

## `wam_recall`

Pack: clinic,business · Category: UTILITY · Language: en

```
Hi {{1}}, it's time for your {{2}}. Free slots: {{3}}. Reply 1, 2 or 3 and I'll book it.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | name | Rahul |
| `{{2}}` | service | Cleaning recall |
| `{{3}}` | slots | 1) Mon 12 Oct, 10:00 AM |

## `wam_doctor_unavailable`

Pack: clinic · Category: UTILITY · Language: en

```
Sorry, {{1}} can't make your {{2}} visit. New slots: {{3}}. Reply 1, 2 or 3 to rebook.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | resource | Dr. Mehta |
| `{{2}}` | time | Fri 16 Oct, 5:00 PM |
| `{{3}}` | slots | 1) Mon 19 Oct, 10:00 AM |

## `wam_booking_confirmation`

Pack: all · Category: UTILITY · Language: en

```
Booked: {{1}}, {{2}} at {{3}}. Reply here if you need to change it.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | service | Root canal (visit 2 of 3) |
| `{{2}}` | date | Mon 12 Oct |
| `{{3}}` | time | 10:00 AM |

## `wam_running_late`

Pack: all · Category: UTILITY · Language: en

```
Update: {{1}} is running about {{2}} minutes late today, so your {{3}} visit may start a little later. Thank you for your patience.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | resource | Dr. Mehta |
| `{{2}}` | minutes | 20 |
| `{{3}}` | time | 5:30 PM |

## `wam_staff_alert`

Pack: all · Category: UTILITY · Language: en

```
WAM update for {{1}}: {{2}}. Reply here to see the details.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | business | Smile Dental |
| `{{2}}` | summary | Today's list is ready for attendance marking |

## `wam_announcement`

Pack: institute · Category: UTILITY · Language: en

```
Update for {{1}}: {{2}}. Reply here if you have questions.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | batch | NEET-A2 |
| `{{2}}` | message | Tomorrow's class starts at 8 AM |

## `wam_absence_alert`

Pack: institute · Category: UTILITY · Language: en

```
Attendance alert: {{1}} was marked absent in {{2}} today. Reply here if this is a mistake.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | student | Aarav |
| `{{2}}` | class | Physics |

## `wam_test_result`

Pack: institute · Category: UTILITY · Language: en

```
Test result: {{1}} scored {{2}} in {{3}}. Reply here to talk to the teacher.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | student | Aarav |
| `{{2}}` | score | 82/100 |
| `{{3}}` | test | Physics unit test 3 |

## `wam_fee_reminder`

Pack: institute · Category: UTILITY · Language: en

```
Installment of {{1}} is due on {{2}}. Reply here if you have already paid.
```

| Variable | Meaning | Example |
| --- | --- | --- |
| `{{1}}` | amount | Rs 12,000 |
| `{{2}}` | date | 15 Oct |
