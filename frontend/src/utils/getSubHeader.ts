export function getWidgetSubheader(field: string): string {
  switch (field) {
    case 'creative_upload':
      return 'Upload image, photo or anything'
    case 'media_buying_confirm':
      return 'Choose a publishing option.'
    case 'campaign_plan_confirm':
      return 'Review your campaign plan.'
    case 'campaign_publish_mode':
      return "Choose how you'd like Punk to prepare your campaign."
    case 'meta_go_live_confirm':
      return 'Review your campaign before it goes live.'
    case 'campaign_budget_amount':
      return 'Choose your daily budget.'
    case 'campaign_website_url':
      return 'Enter your website URL.'
    case 'campaign_app_store_url':
      return "Enter your app's store link."
    case 'campaign_business_name':
      return 'Enter your business name.'
    case 'geo_store_address_for_competitors':
      return 'Enter one or more business addresses.'
    case 'geo_targeting_method':
      return 'Choose a targeting strategy.'
    case 'geo_location_type':
      return 'Select a location type.'
    case 'geo_locations':
      return 'Review selected locations.'
    case 'geo_business_description':
      return 'Describe your business.'
    case 'geo_deterministic_type':
      return 'Select audience signals.'
    case 'geo_poi_types':
      return 'Choose relevant locations.'
    case 'geo_store_addresses':
      return 'Review business locations.'
    case 'geo_brand_names':
      return 'Enter competitor brands.'
    case 'geo_event_type':
      return 'Choose relevant events.'
    case 'campaign_pixel_id':
      return 'Enter your pixel ID.'
    case 'campaign_objective':
      return 'Select campaign objective.'
    default:
      return ''
  }
}