import {
  ShoppingCart,
  MapPin,
  Utensils,
  LayoutGrid,
  Home,
  Coffee,
  Building2,
  Flame,
  ShoppingBag,
} from 'lucide-react'

export const PROMPT_CATEGORIES = [
  {
    label: 'Ecom',
    icon: ShoppingCart,
    prompts: [
      {
        title: "Poaching shoppers straight out of your competitor's stores",
        text: "I own a makeup ecom shop selling clean beauty products. I want to reach women 18-35 who have visited a Sephora or Ulta in NYC at least twice in the last 30 days."
      },
      {
        title: "Turning real-world event crowds into online customers",
        text: "I run an online sneaker marketplace. Target Instagram users who went to both SneakerCon and Flight Club in New York in the last 6 months."
      },
      {
        title: "Reaching people already spending big in your category",
        text: "I sell peptide wellness products. I want to run facebook ads to men 35-60 who visited a longevity clinic, IV therapy lounge, or hormone clinic in Scottsdale in the last 90 days."
      },
      {
        title: "Stacking real-world behaviors to find your highest-intent buyers",
        text: "I sell custom dog gear online. Target people who visited a vet clinic, PetSmart, and a dog park all within the last 45 days in Denver."
      },
      {
        title: "Turning a buyer's lifestyle habit into ultra-targeted ads",
        text: "I have a Shopify store selling personalized dog collars and tags. Target people in Denver who visited a dog park in the last 90 days."
      }
    ]
  },
  {
    label: 'Retail',
    icon: ShoppingBag,
    prompts: [
      {
        title: "Retargeting everyone who's actually walked into your store",
        text: "I own a women's clothing store in LA. I want to show meta ads to every single person that's come into my store over the past 2 weeks."
      },
      {
        title: "Catching buyers at the exact life event that triggers spending",
        text: "I own a furniture store in Atlanta. Target people who visited an open house or a moving truck rental in the last 30 days."
      },
      {
        title: "Converting the gym crowd down the street into walk-ins",
        text: "I run a supplement store in Miami. Target people who visited a gym 3+ times in the last two weeks within 10 minutes of my shop."
      },
      {
        title: "Intercepting brides mid-planning before competitors reach them",
        text: "I run a bridal boutique in Nashville. I want to reach women 24-38 who visited a wedding venue, a jeweler, and a bridal show in the last 6 months."
      },
      {
        title: "Selling to parents already paying for kids' fun",
        text: "I own a kids' toy store. Target parents who visited an indoor playground, a trampoline park, or a children's museum in the last 30 days."
      }
    ]
  },
  {
    label: 'Restaurants',
    icon: Utensils,
    prompts: [
      {
        title: "Turning stadium crowds into barstool regulars",
        text: "I own a sports bar in Kansas City. Show facebook ads to people who were at the last three Chiefs home games. Season ticket holders live at my bar on away weekends."
      },
      {
        title: "Stealing the Starbucks line two blocks away",
        text: "I run a coffee shop in Denver. I want to reach people who go to the Starbucks two blocks from me every weekday before 9am."
      },
      {
        title: "Owning the late-night campus routine",
        text: "I own a ramen shop in Toronto, primarily serving college students. Target students 18-25 who are on campus past 8pm at least three nights a week."
      },
      {
        title: "Catching hungry bar-goers at the perfect moment",
        text: "I run a shawarma spot downtown. Target people who've been at a bar for 3+ hours on a Friday or Saturday night within walking distance of my shop."
      },
      {
        title: "Cloning your best customers while excluding existing ones",
        text: "I run a smoothie and açai bowl chain in Florida. Target white women 18-45 who visited a Pilates studio or a beach volleyball court in the last two weeks. Make sure they haven't already been to one of my stores."
      }
    ]
  },
  {
    label: 'Local Service',
    icon: MapPin,
    prompts: [
      {
        title: "Absorbing a dead competitor's entire member base",
        text: "I run a gym in Minneapolis. The LA Fitness a mile away just closed. Target everyone who was going there 2+ times a week before it shut down."
      },
      {
        title: "Turning parked cars into booked appointments",
        text: "I run a mobile car detailing business in Dallas. Target people who park at office towers with outdoor lots downtown every weekday. I detail their car while they work."
      },
      {
        title: "Detecting broken appliances before anyone Googles a repair",
        text: "I own an appliance repair company in Columbus. Target homeowners who suddenly started going to a laundromat in the last two weeks after never going before."
      },
      {
        title: "Filling dead weekdays by targeting availability, not just interest",
        text: "I own a nail salon in Miami. My Tuesdays and Wednesdays are empty. Target women who visit salons like mine, but only ones whose visits happen on weekdays."
      },
      {
        title: "Winning back regulars who quietly churned",
        text: "I run a barbershop in Brooklyn. Target men who used to come to my shop every 3 weeks but haven't been in over two months."
      }
    ]
  },
  {
    label: 'SaaS',
    icon: LayoutGrid,
    prompts: [
      {
        title: "Separating owners from customers by hours spent inside",
        text: "I created a scheduling software for barbershops. Target people who are inside a barbershop 40+ hours a week, those are the owners and managers, not the customers."
      },
      {
        title: "Turning a trade show badge scan into an ad audience",
        text: "I sell POS to restaurants. Target people who attended the National Restaurant Association Show in Chicago."
      },
      {
        title: "Reaching contractors through their weekly supply runs",
        text: "I sell software for HVAC contractors. Target people who visit HVAC supply houses like Ferguson or Johnstone multiple times a week."
      },
      {
        title: "Targeting founders by where they work, not their job title",
        text: "I created a bookkeeping tool for startups. Target people who work out of WeWorks and co-working spaces in San Francisco, aged 22-40."
      },
      {
        title: "Spotting multi-unit managers by movement patterns alone",
        text: "I sell franchise management software. Target people who show up at multiple locations of the same restaurant chain every week. Those are the managers, not the customers."
      }
    ]
  },
  {
    label: 'Real Estate',
    icon: Home,
    prompts: [
      {
        title: "Filtering serious buyers from Sunday browsers",
        text: "I'm a real estate agent in Miami. Send meta ads to people who've been to 3 or more open houses in the last month."
      },
      {
        title: "Capturing out-of-state buyers while they're physically in town",
        text: "How do I reach out-of-state buyers touring neighborhoods in Scottsdale this winter?"
      },
      {
        title: "Catching sellers before their house ever hits the market",
        text: "I sell condos to old folks in Sarasota. Find empty nesters in big suburban houses who've been visiting 55+ communities or marinas lately."
      },
      {
        title: "Reaching buyers the moment they get serious",
        text: "I'm a realtor in Austin. Find people who visited a mortgage broker in the last 30 days."
      },
      {
        title: "Retargeting your billboard's real-life audience online",
        text: "I'm a realtor in Bel Air. I have a billboard on the corner of Moraga Drive next to the highway. Target everyone who drives past it daily."
      }
    ]
  },
  {
    label: 'B2B',
    icon: Building2,
    prompts: [
      {
        title: "Reaching business owners through their own front doors",
        text: "I run a wholesale coffee roasting company. Target people who own cafés in Chicago."
      },
      {
        title: "Turning one conference into a complete prospect list",
        text: "Target everyone who attended the SHRM conference in Las Vegas last month."
      },
      {
        title: "Putting your product in front of a room full of exact-fit buyers",
        text: "I work for an HR software company. Target everyone who attended the SHRM conference in Las Vegas last month."
      },
      {
        title: "Finding decision-makers by how they move, not what LinkedIn says",
        text: "I have a staffing agency for warehouses in Memphis. Target people who visit 2+ different industrial parks a week. I'm trying to reach ops managers juggling labor across sites."
      },
      {
        title: "Prospecting the operators, not the members",
        text: "I sell commercial cleaning supplies. Target people who run gyms and fitness studios in Dallas."
      }
    ]
  },
  {
    label: 'Vibecoders',
    icon: Coffee,
    prompts: [
      {
        title: "Launching your app to the exact people it was built for",
        text: "I built a pickleball court booking app over a weekend. I want to get my first users. Only target people who've played at a pickleball court in Austin in the last 30 days."
      },
      {
        title: "Seeding your marketplace where supply and demand already meet",
        text: "I made a dog walking marketplace with Lovable. I need dog owners in Chicago as users, so target people that frequent dog parks."
      },
      {
        title: "Acquiring users mid-habit, not mid-scroll",
        text: "I launched a golf score tracker and want users. Get it in front of men 25-55 who played 2 different courses in Phoenix this month."
      },
      {
        title: "Skipping interest targeting and going straight to the niche's home turf",
        text: "I built a workout tracker for powerlifters. Find me users at the hardcore gyms."
      },
      {
        title: "Targeting the professional, not the customer, in the same building",
        text: "I made a booking tool for barbershops. My users are barbers, not people getting their hair cut. Find me people who spend all day inside barbershops in NYC."
      }
    ]
  },
  {
    label: 'WTF',
    icon: Flame,
    prompts: [
      {
        title: "Targeting the visitors of one single address",
        text: "Show my ad to everyone that's been to Drake's mansion in Toronto in the past week."
      },
      {
        title: "Proving no audience is too niche to build",
        text: "Target lesbian tree planters in British Colombia."
      },
      {
        title: "Syncing ads to a payday behavior pattern",
        text: "Target people who visit the casino on payday, every payday."
      },
      {
        title: "Reaching people by where they've been cleared to eat lunch",
        text: "Show my ad to everyone who's been inside the Pentagon food court."
      },
      {
        title: "Finding people who were somewhere they shouldn't be",
        text: "Target everyone who's been to Buckingham Palace after visiting hours."
      }
    ]
  }
]
