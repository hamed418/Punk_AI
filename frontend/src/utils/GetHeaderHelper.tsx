import {
    BadgeCheck,
    Building2,
    CalendarDays,
    ChartNoAxesCombined,
    Crosshair,
    Eye,
    FileText,
    Globe,
    ImageIcon,
    Map,
    MapPin,
    MapPinCheck,
    Network,
    Radar,
    Rocket,
    Smartphone,
    Store,
    Tag,
    Target,
    Wallet,
    Info,
  } from 'lucide-react'
  
  const ICON_SIZE = 16
  export default function GetHeaderHelper(field: string) {
    switch (field) {
      case 'creative_upload':
        return <ImageIcon size={ICON_SIZE} />
      case 'media_buying_confirm':
        return <Rocket size={ICON_SIZE} />
      case 'campaign_plan_confirm':
        return <BadgeCheck size={ICON_SIZE} />
      case 'campaign_publish_mode':
        return <Network size={ICON_SIZE} />
      case 'meta_go_live_confirm':
        return <Eye size={ICON_SIZE} />
      case 'geo_competitor_store_confirmation':
        return <BadgeCheck size={ICON_SIZE} />
      case 'campaign_budget_amount':
        return <Wallet size={ICON_SIZE} />
      case 'campaign_website_url':
        return <Globe size={ICON_SIZE} />
      case 'campaign_app_store_url':
        return <Smartphone size={ICON_SIZE} />
      case 'campaign_business_name':
        return <Building2 size={ICON_SIZE} />
      case 'geo_store_address_for_competitors':
        return <MapPin size={ICON_SIZE} />
      case 'geo_store_confirmation':
        return <Store size={ICON_SIZE} />
      case 'geo_targeting_method':
        return <Target size={ICON_SIZE} />
      case 'geo_location_type':
        return <Map size={ICON_SIZE} />
      case 'geo_locations':
        return <MapPinCheck size={ICON_SIZE} />
      case 'geo_business_description':
        return <FileText size={ICON_SIZE} />
      case 'geo_deterministic_type':
        return <ChartNoAxesCombined size={ICON_SIZE} />
      case 'geo_poi_types':
        return <MapPin size={ICON_SIZE} />
      case 'geo_store_addresses':
        return <Store size={ICON_SIZE} />
      case 'geo_brand_names':
        return <Tag size={ICON_SIZE} />
      case 'geo_event_type':
        return <CalendarDays size={ICON_SIZE} />
      case 'campaign_pixel_id':
        return <Radar size={ICON_SIZE} />
      case 'campaign_objective':
        return <Crosshair size={ICON_SIZE} />
      case 'geo_disambiguate_location':
        return <MapPin size={ICON_SIZE} />
      default:
        return <Info size={ICON_SIZE} />
    }
  }
  
  