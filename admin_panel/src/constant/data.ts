import type { Block } from "../types/chat";

export const swarma: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I own a shawarma shop in a very busy area downtown. I just updated my menu to keep up with the trends because I have seen a decrease in my sales over the last few months. I want to be able to show all the shawarma lovers in my city that go to all my competitors' locations the new items I have added and the discounts I'm giving out to let them try it. Can I simply just target all of my competitors' customers around my store?",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Yes, I can definitely help you find those people. Let’s build this campaign to hit exactly the shawarma lovers who are already going to your competitors. We have three main ways to do this on Meta: Pin Point, Category, Target by Location. Which one feels right for you, or do you want to stick with Pin Point?",
  },
  {
    id: "widget-direction-2",
    type: "pending_action",
    content: {
      action_type: "option_selection",
      prompt: "Which one feels right for you, or do you want to stick with Pin Point?",
      options: [
        "Pin Point: finds people who visited your specific competitors (most precise)",
        "Category: finds anyone who visits any shawarma spot in the city (bigger reach)",
        "Target by Location: broader area targeting without focusing on specific shops",
      ],
    },
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content: "Stick with Pin Point. I want the people going to my competitors.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content:
      "Perfect. Let’s get this started. What’s the name of your shawarma shop?",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "Shawarma Palace.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content:
      "Got it. There might be more than one — what’s the exact address so I can lock in the right location? (Example: “456 Elm Street, Downtown Seattle”)",
  },
  {
    id: "7",
    type: "message",
    role: "user",
    content: "456 Elm Street, Downtown Seattle.",
  },
  // {
  //   id: "split-8-location",
  //   type: "split-map",
  //   version: 1,
  //   chat: [
  //     {
  //       id: "8",
  //       type: "message",
  //       role: "assistant",
  //       content: "Location locked. Is this correct?",
  //     },
  //     {
  //       id: "9",
  //       type: "message",
  //       role: "user",
  //       content: "Yes, that’s me.",
  //     },
  //   ],
  //   map: {
  //     id: "map-location",
  //     type: "map",
  //     stage: "select-location",
  //     center: {
  //       lat: 47.6062,
  //       lng: -122.3321,
  //     },
  //     layers: {},
  //   },
  // },
  {
    id: "10",
    type: "message",
    role: "assistant",
    content:
      "Great. How far away from your shop do you want to reach? I recommend a 1 km radius so we can pick up the competitor stores in that zone and still stay local. You can always choose something different like 2 km if you want wider reach.",
  },
  {
    id: "11",
    type: "message",
    role: "user",
    content: "1 km is perfect.",
  },
  {
    id: "12",
    type: "message",
    role: "assistant",
    content: "1 km radius set.",
  },
  {
    id: "map-radius",
    type: "map_data",
    content: {
      action_type: "radius_picker",
      center: {
        lat: 47.6062,
        lng: -122.3321,
      },
      default_radius_km: 1,
      locations: [],
    },
  },
  {
    id: "12.5",
    type: "message",
    role: "assistant",
    content: "Now pulling competitor locations inside that radius.",
  },
  {
    id: "13",
    type: "message",
    role: "assistant",
    content:
      "Here are all the competitors I found in this 1 km radius. Do you want to deselect any, or should I go ahead and find everyone who has been there recently? You can get as specific as you want — even age, gender, or how much time they spent in those locations.",
  },
  {
    id: "map-competitor",
    type: "map_data",
    content: {
      action_type: "confirm_locations",
      locations: [
        {
          id: "1",
          location_name: "Shawarma King",
          lat: 47.6082,
          lng: -122.3351,
          formatted_address: "0.3 km away (Seattle Downtown)",
        },
        {
          id: "2",
          location_name: "Falafel Palace",
          lat: 47.6042,
          lng: -122.3291,
          formatted_address: "0.6 km away (Seattle Downtown)",
        },
        {
          id: "3",
          location_name: "Mediterranean Grill",
          lat: 47.6102,
          lng: -122.3301,
          formatted_address: "0.9 km away (Seattle Downtown)",
        },
        {
          id: "4",
          location_name: "Gyro Spot",
          lat: 47.6022,
          lng: -122.3341,
          formatted_address: "0.4 km away (Seattle Downtown)",
        },
      ],
    },
  },
  {
    id: "14",
    type: "message",
    role: "user",
    content: "Target all of them.",
  },
  {
    id: "15",
    type: "message",
    role: "assistant",
    content:
      "All 4 competitor locations selected. What radius around each shop would you like me to use to find these people, and how far back would you like me to look? For example, 500 m around each shop and the last 30 days.",
  },
  {
    id: "15.5",
    type: "message",
    role: "user",
    content: "500 m around each shop and the last 30 days.",
  },
  {
    id: "15.75",
    type: "message",
    role: "assistant",
    content:
      "Radius and lookback window set. Before I build the audience, any specific demographics you want to focus on? (I recommend 18–45 for food lovers, but you can narrow it.)",
  },
  {
    id: "16",
    type: "message",
    role: "user",
    content: "18-45 is good.",
  },
  {
    id: "16.5",
    type: "message",
    role: "assistant",
    content:
      "Demographics applied. Running Target People mode on Meta… We’re now finding the group of people who match everything you described.",
  },
  {
    id: "17",
    type: "message",
    role: "assistant",
    content:
      "Great news! I found 8,400 potential customers (94% confidence) who’ve recently visited your competitors inside the 1 km zone. These are real people who physically went there. When the campaign runs, they’ll be the ones seeing your ads — this is Target People mode. To reach all of them effectively, you’ll need a minimum of $600 on this Meta campaign. Does the audience and map look good, or want to adjust anything?",
  },
  {
    id: "map-heatmap",
    type: "map_data",
    content: {
      action_type: "maid_split_view",
      center: { lat: 47.6062, lng: -122.3321, location_name: "Shawarma Palace" },
      pois: [
        { name: "Shawarma King", lat: 47.6082, lng: -122.3351 },
        { name: "Falafel Palace", lat: 47.6042, lng: -122.3291 },
      ],
      maid_count: 8400,
      lookback_days: 30,
      maid_observations: [
        { lat: 47.607, lng: -122.333 },
        { lat: 47.605, lng: -122.331 },
      ],
    },
  },
  {
    id: "18",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "23",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve now identified the right group to show your new menu to. Before we build the full campaign and push it live through Meta (directly from Punk AI — no Ads Manager needed), let’s connect your Meta ad account. This one-time step lets us launch everything straight from here.",
  },
  {
    id: "form-23",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "24",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "25",
    type: "message",
    role: "assistant",
    content:
      "Meta account connected and validated. $600 spend on Meta would be the minimum to be able to reach all 8,400 people. However, because we’re feeding these people into Meta, if you want to spend more, it’ll be very easy for Meta to build incredible lookalike audiences and people similar to your target customers by increasing your ad budget and fueling their algorithm as well — way more accurately than if you didn’t have this audience. Let me know what your monthly budget looks like.",
  },
  {
    id: "26",
    type: "message",
    role: "user",
    content: "$1,200 per month.",
  },
  {
    id: "27",
    type: "message",
    role: "assistant",
    content:
      "Now that we’ve identified the right group, let’s figure out exactly what we’re going to say to them and how the ad should look.",
  },
  {
    id: "quick-question-27",
    type: "pending_action",
    content: {
      action_type: "question_collection",
      prompt: "Ad Setup",
      options: [
        "What’s the main message or creative direction you want?",
        "Preferred ad format? (Single image, carousel, short video, etc.)",
        "Campaign name?",
      ],
    },
  },
  {
    id: "28",
    type: "message",
    role: "user",
    content:
      "Creative: New menu items + big discounts. Format: Carousel. Campaign name: Shawarma Palace Competitor Steal.",
  },
  {
    id: "29",
    type: "message",
    role: "assistant",
    content:
      "Please upload the images or videos you want to use for this carousel campaign (new menu shots, discount offers, food videos — whatever you think will stop the scroll).",
  },
  {
    id: "form-29",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload media",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "30",
    type: "message",
    role: "user",
    content:
      "[Uploads 3 images + 1 short video of the new menu and discount offer]",
  },
  {
    id: "31",
    type: "message",
    role: "assistant",
    content:
      "Creatives uploaded and attached. All right, everything is set. We have your messaging, your creative, and your target audience ready to go. Give me the green light and I’ll activate this campaign through your Meta ad account for you.",
  },
  {
    id: "32",
    type: "message",
    role: "assistant",
    content:
      "Campaign Name: Shawarma Palace Competitor Steal | Audience: Target People from competitor locations | Format: Meta Awareness campaign with POI custom locations | Type “PUSH LIVE” to launch it right now.",
  },
  {
    id: "32-user",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "33",
    type: "message",
    role: "assistant",
    content:
      "Meta Campaign ID: 2385xxxxxxxxxx. You can now watch real-time results (impressions, reach, clicks, cost, conversions) directly in the Campaigns tab inside Punk AI. Want me to keep an eye on it for the first 24 hours and send you a quick performance summary tomorrow?",
  },
];

export const vibe: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I just vibecoded a CRM built for tattoo artists. It helps track their clients progress, follows up with them to help with their healing journey and even reminds me to text them every few months to keep up with them and to see if they want any new tattoos. I would really love to share this product with every tattoo artist in my city before expanding. Would it be possible to send ads to tattoo artists who have been seen at tattoo shops around the city for more than 3 days a week, over the course of the last month? I don't want to target the tattoo shops themselves because then it will also pick up on the client, not just the artist.",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Yes, I can definitely help you find those people. Let’s build this campaign to hit exactly the tattoo artists who are at shops all the time — not the clients. We have three main ways to do this on Meta: Pin Point, Category, and Target by Location. Which one do you want to go with?",
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content:
      "Category. I want every tattoo artist in the city who’s at shops 3+ days a week.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content: "Perfect. Let’s get this started. What city are we targeting?",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "Portland, OR.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content:
      "Location locked to Portland metro area (within 20 km to cover the full city). Now pulling tattoo shops across the metro so we can find the artists who visit them heavily.",
  },
  {
    id: "7",
    type: "message",
    role: "assistant",
    content:
      "Here are the tattoo shops I found in Portland. Do you want to deselect any, or should I go ahead and find everyone who has been there recently?",
  },
  {
    id: "comp-7",
    type: "map_data",
    content: {
      action_type: "confirm_locations",
      locations: [
        { id: "1", location_name: "Ink & Iron Tattoo", lat: 45.5, lng: -122.6 },
        { id: "2", location_name: "Black Rose Tattoo Parlor", lat: 45.5, lng: -122.6 },
      ],
    },
  },
  {
    id: "8",
    type: "message",
    role: "user",
    content: "Target all of them.",
  },
  {
    id: "9",
    type: "message",
    role: "assistant",
    content:
      "All tattoo shops selected. What radius around each shop would you like me to use, and how far back should I look? I recommend 50 m around each shop and the last 30 days to focus on real artists (not one-time clients).",
  },
  {
    id: "10",
    type: "message",
    role: "user",
    content: "50 m around each shop and the last 30 days.",
  },
  {
    id: "11",
    type: "message",
    role: "assistant",
    content:
      "Radius and lookback window set. Any specific demographics for the artists? (I recommend 18-45, but you can narrow it.)",
  },
  {
    id: "12",
    type: "message",
    role: "user",
    content: "18-45 is good.",
  },
  {
    id: "13",
    type: "message",
    role: "assistant",
    content:
      "Demographics applied. Running Target People mode on Meta… Map updates with heatmap showing high-frequency zones and exact count.",
  },
  {
    id: "14",
    type: "message",
    role: "assistant",
    content:
      "Great news! I found 2,150 potential tattoo artists (94% confidence) who visited shops 3+ days a week in the last 30 days. These are the exact high-frequency artists you described. When the campaign runs, they will be the ones seeing your ads — this is Target People mode. To reach all of them effectively, you’ll need a minimum of $500 on this Meta campaign. If $500 feels too high, you can make changes to your audience. Does the audience and map look good as-is, or would you like to change anything?",
  },
  {
    id: "15",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "16",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve locked in the audience to reach. Before we can send off this ad to your audience, we need to set up the campaign requirements from Meta.",
  },
  {
    id: "form-16",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "17",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "18",
    type: "message",
    role: "assistant",
    content:
      "Meta account connected. $500 is the minimum to reach all 2,150 artists. Spending more will also help Meta build strong lookalike audiences from this data. What’s your monthly budget for this campaign?",
  },
  {
    id: "19",
    type: "message",
    role: "user",
    content: "$900 per month.",
  },
  {
    id: "20",
    type: "message",
    role: "assistant",
    content:
      "Budget set. Now that we’ve identified the right group, let’s figure out exactly what we’re going to say to them and how the ad should look.",
  },
  {
    id: "21",
    type: "message",
    role: "user",
    content:
      "Creative direction: Tattoo artist CRM that tracks clients, healing, and rebooking — built for you. Carousel format. Campaign name: Portland Tattoo Artists CRM Traffic.",
  },
  {
    id: "22",
    type: "message",
    role: "assistant",
    content:
      "Plan ready. Objective: Traffic (to website). Audience: 2,150 Target People — high-frequency tattoo artists. Targeting: All Portland tattoo shops + 50 m radius. Creative direction: Tattoo artist CRM that tracks clients, healing, and rebooking — built for you. Ad format: Carousel.",
  },
  {
    id: "23",
    type: "message",
    role: "assistant",
    content:
      "Ad Creative Step (Manual Only): Please upload your creatives (plus CRM screenshots or short clips so artists can instantly see how it works).",
  },
  {
    id: "form-23",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload creatives",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "24",
    type: "message",
    role: "user",
    content: "[Uploads creatives + CRM screenshots]",
  },
  {
    id: "25",
    type: "message",
    role: "assistant",
    content:
      "Creatives uploaded and attached. All right, everything is set. We have your audience, messaging, and creative ready to go. Give me the green light and I’ll activate this campaign through your Meta ad account. Type 'PUSH LIVE' to launch it now.",
  },
  {
    id: "26",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "27",
    type: "message",
    role: "assistant",
    content:
      "Campaign pushed LIVE on Meta! Meta Campaign ID: 2385xxxxxxxxxx. You can now track real-time results (impressions, reach, link clicks, cost, conversions) directly in the Campaigns tab inside Punk AI. Want me to keep an eye on it for the first 24–48 hours and send you a quick performance summary?",
  },
];

export const rock_bank: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I manage a punk rock band. We are going on tour in a few months. I would love to be able to advertise our shows to every city we go to by seeing the last punk rock show they threw in that city and just targeting anyone who went to it and people with similar interests as them.",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Got it — I think you want an Engagement campaign on Meta to promote your upcoming tour shows by targeting people who actually attended the last punk rock show in each city (plus similar high-interest fans).There are multiple ways to do this on Meta:",
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content:
      "Engagement. I want the people who went to the last punk shows in each city.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content:
      "Perfect. Let’s get this started.List the cities and approximate dates for your tour shows. (Example: “Seattle June 15, Portland June 22, Austin July 10”)",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "Seattle June 15, Portland June 22, Austin July 10.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content:
      "Tour locked: Seattle (June 15), Portland (June 22), Austin (July 10). Now running web search for the most recent punk rock shows in each city so we can find the exact fans who were there.",
  },
  {
    id: "comp-6",
    type: "map_data",
    content: {
      action_type: "confirm_locations",
      locations: [
        { id: "1", location_name: "The Crocodile", lat: 47.6, lng: -122.3 },
        { id: "2", location_name: "Dante’s", lat: 45.5, lng: -122.6 },
      ],
    },
  },
  {
    id: "7",
    type: "message",
    role: "user",
    content: "Target all of them.",
  },
  {
    id: "7.5",
    type: "message",
    role: "assistant",
    content:
      "All venues confirmed. Here are the target points I've mapped out for your tour shows. Now let's define the reach around each location.",
  },
  {
    id: "8",
    type: "message",
    role: "assistant",
    content:
      " All 3 venues selected. How far around each venue do you want me to look for the people who attended? I recommend 500 m so we stay focused on real fans who were actually there.",
  },
  {
    id: "9",
    type: "message",
    role: "user",
    content: "500 m is good.",
  },
  {
    id: "10",
    type: "message",
    role: "assistant",
    content:
      " Radius set to 500 m per venue. Running Target People mode on Meta… Our agents are now going through our data and finding the exact people who physically attended those last punk shows in each city.I found 11,200 real punk fans (96% confidence) who were physically at the last punk shows in Seattle, Portland, and Austin. These are the exact people you want: real fans who showed up to the last shows, not just people who “like” punk online. When the campaign runs, they will be the ones seeing your tour ads — this is Target People mode at its best. To reach all of them effectively, you’ll need a minimum of $700 on this Meta campaign. If $700 feels too high, you can make changes to your audience. Does the audience and map look good as-is, or would you like to make changes?",
  },
  {
    id: "11",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "12",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve now identified the right group of real punk fans. Before we build the campaign and launch it through Meta, let’s connect your Meta ad account (one-time step — super easy, just one click and you’re done).",
  },
  {
    id: "form-12",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "13",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "14",
    type: "message",
    role: "assistant",
    content:
      " Meta account connected. $700 is the minimum to reach all 11,200 fans. Spending more will also help Meta build strong lookalike audiences from this data. What’s your monthly budget for this tour campaign?",
  },
  {
    id: "15",
    type: "message",
    role: "user",
    content: "$1,400 per month.",
  },
  {
    id: "16",
    type: "message",
    role: "assistant",
    content:
      "Now that we’ve found the right people, let’s figure out exactly what we’re going to say to them and how the ad should look.",
  },
  {
    id: "17",
    type: "message",
    role: "user",
    content:
      "Creative direction: Your city’s last punk show was fire… wait till you see ours. Video format. Campaign name: Punk Tour 2026.",
  },
  {
    id: "18",
    type: "message",
    role: "assistant",
    content:
      "Plan ready. Objective: Engagement. Audience: 11,200 punk fans. Targeting: selected venues + 500 m radius. Ad format: Video. Please upload your creatives.",
  },
  {
    id: "form-18",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload media",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "19",
    type: "message",
    role: "user",
    content: "[Uploads creatives]",
  },
  {
    id: "20",
    type: "message",
    role: "assistant",
    content:
      "All right, everything is set. We have your audience, messaging, and creative ready to go. Give me the green light and I’ll activate this campaign through your Meta ad account. Type “PUSH LIVE” to launch it now.",
  },
  {
    id: "21",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "22",
    type: "message",
    role: "assistant",
    content:
      "Meta Campaign ID: 2385xxxxxxxxxx You can now track real-time results (impressions, reach, post engagements, link clicks, cost) directly in the Campaigns tab inside Punk AI. Want me to monitor performance across all three cities and send you a summary after the first 48 hours?",
  },
];

export const realEstateLeads: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I'm a real estate agent, I run free home valuation ads at home sellers.",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Yes, I can definitely help you find those people. Let’s build this campaign to reach potential home sellers with your free home valuation offer.",
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content:
      "Leads. I want people to fill out the form for the free valuation.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content:
      "Perfect. Let’s get this started. What city or metro area are you targeting?",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "Austin, TX metro.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content: "Location locked to Austin metro area",
  },
  {
    id: "7",
    type: "message",
    role: "user",
    content: "Select the top 50 neighborhoods.",
  },
  {
    id: "8",
    type: "message",
    role: "assistant",
    content:
      "Top 50 neighborhoods selected. How far around each neighborhood do you want me to look? Since you’re going broad, I recommend 1 km so we reach people who actually live or spend time there.",
  },
  {
    id: "9",
    type: "message",
    role: "user",
    content: "Keep it at 1 km.",
  },
  {
    id: "10",
    type: "message",
    role: "assistant",
    content:
      "Radius set to 1 km. Any specific demographics you want to focus on? (For home valuation leads, most agents target 35–65 year olds, but you can narrow it.)",
  },
  {
    id: "11",
    type: "message",
    role: "user",
    content: "35-65 is good.",
  },
  {
    id: "12",
    type: "message",
    role: "assistant",
    content: "Demographics applied. Running Target People mode on Meta…",
  },
  {
    id: "13",
    type: "message",
    role: "assistant",
    content:
      "Great news! I found 14,600 potential customers (92% confidence) in those 50 neighborhoods who match the profile of people likely to be thinking about selling. These are real people who live or spend time in areas with active home sales. When the campaign runs, they will be the ones seeing your free home valuation ads — this is Target People mode. To reach all of them effectively, you’ll need a minimum of $800 on this Meta campaign. If $800 feels too high, you can make changes to your audience. Does the audience and map look good as-is, or would you like to make changes?",
  },
  {
    id: "14",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "15",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve now identified the right group. Before we can send off this ad to your audience, we need to set up the campaign requirements from Meta.",
  },
  {
    id: "form-15",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "16",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "17",
    type: "message",
    role: "assistant",
    content:
      "Meta account connected. $800 is the minimum to reach all 14,600 people. Spending more will also help Meta build strong lookalike audiences from this data. What’s your monthly budget for this campaign?",
  },
  {
    id: "18",
    type: "message",
    role: "user",
    content: "$1,800 per month.",
  },
  {
    id: "19",
    type: "message",
    role: "assistant",
    content: "Budget set.",
  },
  {
    id: "20",
    type: "message",
    role: "assistant",
    content:
      "Now that we’ve found the right people, let’s figure out exactly what we’re going to say to them and how the ad should look.",
  },
  {
    id: "21",
    type: "message",
    role: "user",
    content:
      "Creative direction: “Get a free home valuation in minutes — see what your house is worth today.” Carousel format. Campaign name: Austin Free Home Valuation Leads.",
  },
  {
    id: "22",
    type: "message",
    role: "assistant",
    content:
      "Plan ready. Objective: Lead Generation. Audience: 14,600 people. Targeting: top 50 neighborhoods + 1 km radius. Ad format: Carousel. Please upload creatives.",
  },
  {
    id: "form-22",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload media",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "23",
    type: "message",
    role: "user",
    content: "[Uploads creatives]",
  },
  {
    id: "24",
    type: "message",
    role: "assistant",
    content:
      "Creatives uploaded and attached. Lead Form is now configured and ready. All right, everything is set. We have your audience, messaging, and creative ready to go. Give me the green light and I’ll activate this campaign through your Meta ad account. Type “PUSH LIVE” to launch it now.",
  },
  {
    id: "25",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "26",
    type: "message",
    role: "assistant",
    content:
      "Campaign pushed LIVE on Meta! Meta Campaign ID: 2385xxxxxxxxxx. You can now track real-time results (impressions, reach, leads generated, cost per lead) directly in the Campaigns tab inside Punk AI. Want me to monitor it for the first 24–48 hours and send you a quick performance summary with the number of leads captured?",
  },
];

export const game: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I just built an insane game in roblox, posted the link on Twitter, and only got 12 likes. I’d be down to spend like 300$ to see if I could advertise this on Meta to gamers. What should I do?",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Yes, I can definitely help you find those people. With a $300 budget, the smartest move is to keep it hyper-local and focused on real gamers who already hang out at gaming spots. There are multiple ways to do this on Meta: App Promotion, Traffic, and Awareness. Which one do you want to go with?",
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content: "App Promotion. I want people to play the game.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content:
      "Perfect. Let’s get this started. What city or metro area do you want to target gamers in?",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "Chicago metro.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content:
      "Location locked to Chicago metro area. Found gaming spots like gaming cafes, esports lounges, arcades, and university gaming clubs. Do you want to refine or proceed?",
  },
  {
    id: "7",
    type: "message",
    role: "user",
    content: "Select the top 40 gaming spots.",
  },
  {
    id: "7.5",
    type: "message",
    role: "assistant",
    content:
      "Gaming locations locked. I've pinned all 40 hotspots across Chicago. With these selected, we'll now set a tight radius to maximize your $300 budget.",
  },
  {
    id: "8",
    type: "message",
    role: "assistant",
    content:
      "Top 40 gaming spots selected. With a $300 budget, we’ll need to keep targeting tight. What radius should we use? I recommend 20–50 m.",
  },
  {
    id: "9",
    type: "message",
    role: "user",
    content: "Keep it at 50 m.",
  },
  {
    id: "10",
    type: "message",
    role: "assistant",
    content:
      "Radius set to 50 m. Any age range? Most Roblox players are 13–24.",
  },
  {
    id: "11",
    type: "message",
    role: "user",
    content: "13-24 is good.",
  },
  {
    id: "12",
    type: "message",
    role: "assistant",
    content:
      "Demographics applied. Running Target People mode… Found 9,300 gamers (93% confidence) who visit these spots. With your $300 budget, we’ll keep delivery tight. Does the audience look good?",
  },
  {
    id: "13",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "14",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve identified the right audience. Please connect your Meta ad account to proceed.",
  },
  {
    id: "form-14",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "15",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "16",
    type: "message",
    role: "assistant",
    content:
      "Meta account connected. Let’s define your ad creative. What’s the hook, format, campaign name, and game link?",
  },
  {
    id: "17",
    type: "message",
    role: "user",
    content:
      "Creative direction: “Just built this insane Roblox game — come play it now!” Video format. Campaign name: Chicago Roblox Game Launch. Link: roblox.com/games/1234567890/MyInsaneGame",
  },
  {
    id: "18",
    type: "message",
    role: "assistant",
    content:
      "Plan ready. Objective: App Promotion. Audience: 9,300 gamers. Targeting: top 40 gaming spots + 50 m radius. Ad format: Video. Link attached. Please upload creatives.",
  },
  {
    id: "form-18",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload media",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "19",
    type: "message",
    role: "user",
    content: "[Uploads creatives]",
  },
  {
    id: "20",
    type: "message",
    role: "assistant",
    content:
      "Creatives uploaded. Roblox game link attached. Type 'PUSH LIVE' to launch.",
  },
  {
    id: "21",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "22",
    type: "message",
    role: "assistant",
    content:
      "Campaign pushed LIVE on Meta! Your $300 budget is active. You can now track impressions, clicks, and engagement. Want me to monitor performance and send a 48-hour report?",
  },
];

export const matcha: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I just launched my matcha brand in LA. I want to target matcha drinkers in the city. I’m thinking primarily of women 16-35.",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Yes, I can definitely help you find those people. Let’s build this campaign to reach real matcha drinkers in LA and drive direct sales. There are multiple ways to do this on Meta: Sales, Traffic, and Awareness. Which one do you want to go with?",
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content: "Sales. I want people to actually buy the matcha.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content:
      "Perfect. Let’s get this started. What city or metro area are you targeting?",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "LA metro.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content:
      "Location locked to LA metro area. Found matcha cafés, wellness spots, yoga studios, and health stores. Do you want to refine or proceed?",
  },
  {
    id: "7",
    type: "message",
    role: "user",
    content: "Select the top 60.",
  },
  {
    id: "8",
    type: "message",
    role: "assistant",
    content:
      "Top 60 spots selected. What radius should we use? I recommend 1 km.",
  },
  {
    id: "9",
    type: "message",
    role: "user",
    content: "Keep it at 1 km.",
  },
  {
    id: "10",
    type: "message",
    role: "assistant",
    content: "Radius set to 1 km. Confirming demographics: women 16–35?",
  },
  {
    id: "11",
    type: "message",
    role: "user",
    content: "Women 16-35 is perfect.",
  },
  {
    id: "12",
    type: "message",
    role: "assistant",
    content:
      "Demographics applied. Running Target People mode… Found 12,400 matcha drinkers (93% confidence). Minimum budget is $900. Does the audience look good?",
  },
  {
    id: "13",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "14",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve identified the right audience. Please connect your Meta ad account to proceed.",
  },
  {
    id: "form-14",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "15",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "16",
    type: "message",
    role: "assistant",
    content:
      "Meta account connected. What’s your monthly budget for this campaign?",
  },
  {
    id: "17",
    type: "message",
    role: "user",
    content: "$2,000 per month.",
  },
  {
    id: "18",
    type: "message",
    role: "assistant",
    content:
      "Budget set. Now let’s define your ad creative. What’s the headline, format, campaign name, and website link?",
  },
  {
    id: "19",
    type: "message",
    role: "user",
    content:
      "Creative direction: Fresh matcha, real energy — try it today. Carousel format. Campaign name: LA Matcha Launch Sales. Link: matchalove.com/shop",
  },
  {
    id: "20",
    type: "message",
    role: "assistant",
    content:
      "Plan ready. Objective: Sales. Audience: 12,400 matcha drinkers. Targeting: top 60 spots + 1 km radius. Ad format: Carousel. Link attached. Please upload creatives.",
  },
  {
    id: "form-20",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload media",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "21",
    type: "message",
    role: "user",
    content: "[Uploads creatives]",
  },
  {
    id: "22",
    type: "message",
    role: "assistant",
    content:
      "Creatives uploaded. Meta Pixel configured for sales tracking. Type 'PUSH LIVE' to launch.",
  },
  {
    id: "23",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "24",
    type: "message",
    role: "assistant",
    content:
      "Campaign pushed LIVE on Meta! You can now track impressions, clicks, add-to-carts, and purchases. Want me to monitor performance and send a 48-hour sales report?",
  },
];

export const gamble: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I want to promote a hockey promotion for my sports gambling app to men in Montreal. Can we send this ad to men aged 18-45 in the city who have been to a casino and who have also been to a habs game in the last year?",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Yes, I can definitely help you find those people. Let’s build this campaign to reach men 18-45 in Montreal who have been to both a casino and a Habs game. There are multiple ways to do this on Meta: Sales, Traffic, and Awareness. Which one do you want to go with?",
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content: "Sales. I want people to actually use the promotion in the app.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content:
      "Perfect. Let’s get this started. Found Habs games at Bell Centre and casino locations in Montreal. Do you want to target these venues?",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "Select Bell Centre and Casino de Montréal.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content:
      "Selected Bell Centre and Casino de Montréal. What radius should we use? I recommend 1 km.",
  },
  {
    id: "7",
    type: "message",
    role: "user",
    content: "Keep it at 1 km.",
  },
  {
    id: "8",
    type: "message",
    role: "assistant",
    content:
      "Radius set to 1 km. Running Target People mode… Found 4,800 high-intent fans (95% confidence) who visited both locations. Minimum budget is $650. Does the audience look good?",
  },
  {
    id: "9",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "10",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve identified the right audience. Please connect your Meta ad account to proceed.",
  },
  {
    id: "form-10",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "11",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "12",
    type: "message",
    role: "assistant",
    content:
      "Meta account connected. What’s your monthly budget for this campaign?",
  },
  {
    id: "13",
    type: "message",
    role: "user",
    content: "$1,200 per month.",
  },
  {
    id: "14",
    type: "message",
    role: "assistant",
    content:
      "Budget set. Now let’s define your ad creative. What’s the headline, format, campaign name, and app link?",
  },
  {
    id: "15",
    type: "message",
    role: "user",
    content:
      "Creative direction: Habs fans win bigger with this hockey promotion. Video format. Campaign name: Montreal Habs Hockey Promo. Link: myapp.com/habs-promo",
  },
  {
    id: "16",
    type: "message",
    role: "assistant",
    content:
      "Plan ready. Objective: Sales. Audience: 4,800 fans. Targeting: Bell Centre + Casino de Montréal + 1 km radius. Ad format: Video. Link attached. Please upload creatives.",
  },
  {
    id: "form-16",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload media",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "17",
    type: "message",
    role: "user",
    content: "[Uploads creatives]",
  },
  {
    id: "18",
    type: "message",
    role: "assistant",
    content:
      "Creatives uploaded. Meta Pixel configured for conversion tracking. Type 'PUSH LIVE' to launch.",
  },
  {
    id: "19",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "20",
    type: "message",
    role: "assistant",
    content:
      "Campaign pushed LIVE on Meta! You can now track impressions, clicks, and purchases. Want me to monitor performance and send a 48-hour report?",
  },
];

export const ai: Block[] = [
  {
    id: "1",
    type: "message",
    role: "user",
    content:
      "I’m an AI consultant for local service based businesses. I want to show plumbers how I can help them implement AI optimization workflows in their business. Can I only target plumbers and maybe electricians too?",
  },
  {
    id: "2",
    type: "message",
    role: "assistant",
    content:
      "Yes, I can definitely help you find those people. Let’s build this campaign to reach real plumbers and electricians and show them how your AI optimization workflows can transform their businesses. There are multiple ways to do this on Meta: Sales, Traffic, and Awareness. Which one do you want to go with?",
  },
  {
    id: "3",
    type: "message",
    role: "user",
    content: "Sales. I want them to book a call or sign up.",
  },
  {
    id: "4",
    type: "message",
    role: "assistant",
    content:
      "Perfect. Let’s get this started. What city or metro area do you want to target?",
  },
  {
    id: "5",
    type: "message",
    role: "user",
    content: "Chicago metro.",
  },
  {
    id: "6",
    type: "message",
    role: "assistant",
    content:
      "Location locked to Chicago metro. Found trade spots like supply houses, contractor yards, trade counters, and association offices. Do you want to refine or proceed?",
  },
  {
    id: "7",
    type: "message",
    role: "user",
    content: "Select the top 55.",
  },
  {
    id: "8",
    type: "message",
    role: "assistant",
    content:
      "Top 55 trade spots selected. What radius should we use? I recommend 1 km.",
  },
  {
    id: "9",
    type: "message",
    role: "user",
    content: "Keep it at 1 km.",
  },
  {
    id: "10",
    type: "message",
    role: "assistant",
    content:
      "Radius set to 1 km. Running Target People mode… Found 6,900 service pros (93% confidence) who visit these locations. Minimum budget is $650. Does the audience look good?",
  },
  {
    id: "11",
    type: "message",
    role: "user",
    content: "Yes, looks perfect.",
  },
  {
    id: "12",
    type: "message",
    role: "assistant",
    content:
      "Great — we’ve identified the right audience. Please connect your Meta ad account to proceed.",
  },
  {
    id: "form-12",
    type: "pending_action",
    content: {
      action_type: "oauth_connect",
      prompt: "Connect your Meta account",
      options: ["https://meta.com/oauth/connect"],
    },
  },
  {
    id: "13",
    type: "message",
    role: "user",
    content: "[Connects account]",
  },
  {
    id: "14",
    type: "message",
    role: "assistant",
    content:
      "Meta account connected. What’s your monthly budget for this campaign?",
  },
  {
    id: "15",
    type: "message",
    role: "user",
    content: "$1,500 per month.",
  },
  {
    id: "16",
    type: "message",
    role: "assistant",
    content:
      "Budget set. Now let’s define your ad creative. What’s the headline, format, campaign name, and booking link?",
  },
  {
    id: "17",
    type: "message",
    role: "user",
    content:
      "Creative direction: Free AI Workflow Audit for Plumbers and Electricians – Save hours every week. Carousel format. Campaign name: Chicago Service Pros AI Optimization. Link: aiworkflowconsulting.com/book",
  },
  {
    id: "18",
    type: "message",
    role: "assistant",
    content:
      "Plan ready. Objective: Sales. Audience: 6,900 service pros. Targeting: top 55 trade spots + 1 km radius. Ad format: Carousel. Link attached. Please upload creatives.",
  },
  {
    id: "form-18",
    type: "pending_action",
    content: {
      action_type: "file_upload",
      prompt: "Upload media",
      options: ["JPG", "PNG", "MP4"],
    },
  },
  {
    id: "19",
    type: "message",
    role: "user",
    content: "[Uploads creatives]",
  },
  {
    id: "20",
    type: "message",
    role: "assistant",
    content:
      "Creatives uploaded. Meta Pixel configured for lead tracking. Type 'PUSH LIVE' to launch.",
  },
  {
    id: "21",
    type: "message",
    role: "user",
    content: "PUSH LIVE",
  },
  {
    id: "22",
    type: "message",
    role: "assistant",
    content:
      "Campaign pushed LIVE on Meta! You can now track impressions, clicks, and leads. Want me to monitor performance and send a 48-hour report?",
  },
];

export const chat_data: { id: string; title: string; chat: Block[] }[] = [
  { id: "1", title: "Shawarma Palace Campaign", chat: swarma },
  { id: "2", title: "Tattoo Artist CRM", chat: vibe },
  { id: "3", title: "Punk Rock Band Tour", chat: rock_bank },
  { id: "4", title: "Real Estate Valuation", chat: realEstateLeads },
  { id: "5", title: "Gaming Studio App Installs", chat: game },
  { id: "6", title: "Matcha Brand Expansion", chat: matcha },
  { id: "7", title: "Betting App Customer Acq", chat: gamble },
  { id: "8", title: "AI Automation Agency", chat: ai },
];

export const findMockResponse = (content: string) => {
  const normalizedSearch = content
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  for (const thread of chat_data) {
    const flatBlocks = thread.chat;

    for (let i = 0; i < flatBlocks.length; i++) {
      const block = flatBlocks[i];
      if (block.type === "message" && block.role === "user") {
        const normalizedMsg = block.content
          .toLowerCase()
          .replace(/[^a-z0-9\s]/g, "")
          .replace(/\s+/g, " ")
          .trim();
        if (
          normalizedMsg.includes(normalizedSearch) ||
          normalizedSearch.includes(normalizedMsg)
        ) {
          for (let j = i + 1; j < flatBlocks.length; j++) {
            const nextBlock = flatBlocks[j];
            if (
              nextBlock.type === "message" &&
              nextBlock.role === "assistant"
            ) {
              return {
                question: block,
                answer: nextBlock,
                parent: null,
                fullChat: thread.chat,
                currentIndex: j,
                id: thread.id,
              };
            }
          }
        }
      }
    }
  }
  return null;
};

export const findNextUserMessage = (assistantContent: string) => {
  const normalizedSearch = assistantContent
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  for (const thread of chat_data) {
    const flatBlocks = thread.chat;

    for (let i = 0; i < flatBlocks.length; i++) {
      const block = flatBlocks[i];
      if (
        block.type === "message" &&
        block.role === "assistant" &&
        block.content
      ) {
        const normalizedMsg = block.content
          .toLowerCase()
          .replace(/[^a-z0-9\s]/g, "")
          .replace(/\s+/g, " ")
          .trim();
        if (
          normalizedMsg.includes(normalizedSearch) ||
          normalizedSearch.includes(normalizedMsg)
        ) {
          for (let j = i + 1; j < flatBlocks.length; j++) {
            const nextBlock = flatBlocks[j];
            if (nextBlock.type === "message" && nextBlock.role === "user") {
              return nextBlock.content;
            }
          }
        }
      }
    }
  }
  return null;
};
