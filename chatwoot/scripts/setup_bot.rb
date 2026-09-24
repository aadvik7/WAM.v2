# Create (or update) the WAM agent bot for one clinic's WhatsApp inbox and print its token and secret.
# Run inside the Chatwoot container:
#   docker compose run --rm \
#     -e ACCOUNT_ID=1 -e INBOX_ID=1 \
#     -e WAM_WEBHOOK_URL=https://api.example.in/webhooks/chatwoot/<WAM_WEBHOOK_SECRET> \
#     chatwoot bundle exec rails runner /wam/setup_bot.rb
# Then paste the token and secret into WAM admin → Setup → WhatsApp connection.
# (The same can be done by hand in Chatwoot: Settings → Bots → Add bot, then Inbox → Settings → Bot.)

account = Account.find(ENV.fetch('ACCOUNT_ID'))
inbox = account.inboxes.find(ENV.fetch('INBOX_ID'))
url = ENV.fetch('WAM_WEBHOOK_URL')

bot = AgentBot.find_or_initialize_by(account: account, name: 'WAM')
bot.description = 'WAM assistant: answers patients, books visits, sends reminders'
bot.outgoing_url = url
bot.save!

link = AgentBotInbox.find_or_initialize_by(inbox: inbox)
link.agent_bot = bot
link.status = :active
link.save!

token = bot.access_token&.token
puts "Agent bot ##{bot.id} '#{bot.name}' attached to inbox ##{inbox.id} (#{inbox.name})"
puts "Webhook URL:    #{url}"
puts "Bot token:      #{token}"
puts "Webhook secret: #{bot.secret}" if bot.respond_to?(:secret)
