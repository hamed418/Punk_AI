export function getWidgetHeader(field: string): string {
  switch (field) {
    case 'creative_upload':
      return 'Creative Upload'
    case 'media_buying_confirm':
      return 'Publish Campaign'
    case 'campaign_plan_confirm':
      return 'Campaign Review'
    case 'campaign_publish_mode':
      return 'Campaign Setup'
    case 'meta_go_live_confirm':
      return 'Preview & Publish'
    case 'campaign_budget_amount':
      return 'Campaign Budget'
    case 'campaign_website_url':
      return 'Business Website'
    case 'campaign_app_store_url':
      return 'App Store URL'
    case 'campaign_business_name':
      return 'Business Name'
    case 'geo_store_address_for_competitors':
      return 'Business Locations'
    case 'geo_targeting_method':
      return 'Targeting Method'
    case 'geo_location_type':
      return 'Location Type'
    case 'geo_locations':
      return 'Location Confirmation'
    case 'geo_business_description':
      return 'Business Description'
    case 'geo_deterministic_type':
      return 'Audience Signals'
    case 'geo_poi_types':
      return 'Points of Interest'
    case 'geo_store_addresses':
      return 'Business Addresses'
    case 'geo_brand_names':
      return 'Competitor Brands'
    case 'geo_event_type':
      return 'Target Events'
    case 'campaign_pixel_id':
      return 'Pixel ID'
    case 'campaign_objective':
      return 'Campaign Objective'
    default:
      return ''
  }
}