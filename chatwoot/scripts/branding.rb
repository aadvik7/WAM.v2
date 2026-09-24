# Rebrand the Chatwoot inbox as WAM (configure, don't rewrite).
# Run inside the Chatwoot container:
#   docker compose run --rm -e WAM_BRAND_URL=https://inbox.example.in chatwoot \
#     bundle exec rails runner /wam/branding.rb
# Logos are served from /brand-assets (mounted from chatwoot/brand-assets).

brand_url = ENV.fetch('WAM_BRAND_URL', 'https://wam.example.com')

settings = {
  'INSTALLATION_NAME' => 'WAM',
  'BRAND_NAME' => 'WAM',
  'BRAND_URL' => brand_url,
  'WIDGET_BRAND_URL' => brand_url,
  'LOGO_THUMBNAIL' => '/brand-assets/wam-thumbnail.svg',
  'LOGO' => '/brand-assets/wam-logo.svg',
  'LOGO_DARK' => '/brand-assets/wam-logo-dark.svg',
  'TERMS_URL' => ENV.fetch('WAM_TERMS_URL', "#{brand_url}/terms"),
  'PRIVACY_URL' => ENV.fetch('WAM_PRIVACY_URL', "#{brand_url}/privacy"),
  'DISPLAY_MANIFEST' => false,
  'ENABLE_ACCOUNT_SIGNUP' => false
}

settings.each do |name, value|
  config = InstallationConfig.find_or_initialize_by(name: name)
  config.value = value
  config.locked = false if config.respond_to?(:locked=)
  config.save!
  puts "set #{name}"
end

GlobalConfig.clear_cache if GlobalConfig.respond_to?(:clear_cache)
puts 'WAM branding applied.'
