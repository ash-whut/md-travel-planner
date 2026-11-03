import type { ChatMessage, Trip } from './types'

// The example trip from the Phase 2 sketches: College Station -> San Jose, CA.
export const trip: Trip = {
  title: 'San Jose — Tech, Tacos & Gardens',
  dates: 'Fri, Mar 5 – Sun, Mar 7',
  travelers: 1,
  costRange: '$780 – $910',
  weatherSummary: 'Mild and sunny, 48–68 °F',
  version: 2,
  assumptions: ['Budget level assumed (none given)', 'Rideshare for local trips'],
  profile: [
    { label: '📍 San Jose, CA' },
    { label: '🏠 College Station, TX' },
    { label: '📅 Mar 5–7' },
    { label: '👤 1 traveler' },
    { label: '🌱 Vegan' },
    { label: '🎯 tech, food, gardens' },
  ],
  days: [
    {
      dayNumber: 1,
      date: 'Fri, Mar 5',
      title: 'Travel day',
      weather: { icon: '☀️', high: 66, low: 48 },
      items: [
        {
          tag: 'A', place: 'Home', kind: 'transit', startTime: '6:00 AM',
          action: 'Leave from home to Houston IAH airport via Uber.',
          cost: 100, duration: '2 hr',
          why: 'Cheapest door-to-door option; no long-term airport parking for 3 days.',
          source: 'Estimate · Uber fare range',
        },
        {
          tag: 'B', place: 'IAH', kind: 'flight', startTime: '9:15 AM',
          action: 'Board your flight to San Jose.',
          cost: 300, duration: '6 hr', bookable: true,
          why: 'Lowest fare with one stop that lands before 2 PM local time.',
          source: 'Google Flights search link',
        },
        {
          tag: 'C', place: 'San Jose Airport', kind: 'transit', startTime: '1:30 PM',
          action: 'Head to the Marriott Hotel via Uber.',
          cost: 15, duration: '30 min', lat: 37.3639, lng: -121.9289,
          why: 'Hotel is 4 miles away; rideshare beats the shuttle by ~25 min.',
          source: 'Estimate · Google Routes',
        },
        {
          tag: 'D', place: 'San Jose Marriott', kind: 'lodging', startTime: '2:15 PM',
          action: 'Check in — 2 nights downtown.',
          cost: 120, duration: '2 nights', lat: 37.3299, lng: -121.8889, bookable: true,
          why: 'Cheapest 4★ option within walking distance of downtown food.',
          source: 'SerpApi Google Hotels · as of Nov 1, 6:04 PM',
        },
        {
          tag: 'E', place: 'San Pedro Square', kind: 'meal', startTime: '6:30 PM',
          action: 'Dinner at the food hall — lots of vegan stalls.',
          cost: 20, duration: '1.5 hr', lat: 37.3364, lng: -121.8945,
          why: 'Matches "food" interest; 8 min walk from the hotel.',
          source: 'Google Places · 4.5★',
        },
      ],
    },
    {
      dayNumber: 2,
      date: 'Sat, Mar 6',
      title: 'Tech & mystery',
      weather: { icon: '⛅', high: 68, low: 50 },
      items: [
        {
          tag: 'F', place: 'Good Karma Kitchen', kind: 'meal', startTime: '11:00 AM',
          action: 'Vegan brunch, then head to the first tourist spot at 1 PM.',
          cost: 20, duration: '1.5 hr', lat: 37.3352, lng: -121.8880,
          why: 'Replaced Baconhouse after you asked for vegan. Highest-rated vegan spot nearby.',
          source: 'Google Places · 4.7★', updatedInVersion: 2,
        },
        {
          tag: 'G', place: 'The Tech Interactive', kind: 'activity', startTime: '1:00 PM',
          action: 'Hands-on science & tech museum.',
          cost: 32, duration: '2.5 hr', lat: 37.3315, lng: -121.8901, bookable: true,
          why: 'Matches "tech" interest; indoor in case of afternoon clouds.',
          source: 'Google Places · 4.6★',
        },
        {
          tag: 'H', place: 'Winchester Mystery House', kind: 'activity', startTime: '4:00 PM',
          action: 'Guided mansion tour.',
          cost: 46, duration: '1.5 hr', lat: 37.3184, lng: -121.9511, bookable: true,
          why: 'Most-visited sight in San Jose; tours sell out on weekends.',
          source: 'Google Places · 4.4★',
        },
        {
          tag: 'I', place: 'Santana Row', kind: 'meal', startTime: '6:30 PM',
          action: 'Walk the row, dinner at a plant-based bistro.',
          cost: 25, duration: '2 hr', lat: 37.3209, lng: -121.9478,
          why: 'Across the street from H — no extra travel.',
          source: 'Google Places · 4.6★',
        },
      ],
    },
    {
      dayNumber: 3,
      date: 'Sun, Mar 7',
      title: 'Gardens & home',
      weather: { icon: '☀️', high: 67, low: 49 },
      items: [
        {
          tag: 'J', place: 'Japantown', kind: 'meal', startTime: '9:30 AM',
          action: 'Breakfast and a stroll through the farmers market.',
          cost: 15, duration: '1.5 hr', lat: 37.3483, lng: -121.8949,
          why: 'Sunday market only; matches "food".',
          source: 'Google Places · 4.5★',
        },
        {
          tag: 'K', place: 'Guadalupe River Park', kind: 'activity', startTime: '11:15 AM',
          action: 'Rose garden walk before heading out.',
          cost: 0, duration: '1 hr', lat: 37.3405, lng: -121.899,
          why: 'Matches "gardens"; free; on the way to the airport.',
          source: 'Google Places · 4.6★',
        },
        {
          tag: 'C', place: 'San Jose Airport', kind: 'flight', startTime: '2:40 PM',
          action: 'Fly back to Houston IAH.',
          cost: 0, duration: '5.5 hr', lat: 37.3639, lng: -121.9289,
          why: 'Return leg of the round trip booked in B.',
          source: 'Google Flights search link',
        },
      ],
    },
  ],
  bookings: [
    {
      id: 'flight', tags: ['B', 'C'], title: 'Flight Booking',
      estimate: '$300 | 6 hr', detail: 'IAH → SJC round trip · Mar 5 – Mar 7',
      provider: 'Google Flights',
    },
    {
      id: 'hotel', tags: ['D'], title: 'Hotel Booking',
      estimate: '$240 total ($120/night)', detail: 'San Jose Marriott · 2 nights · as of Nov 1, 6:04 PM',
      provider: 'Booking.com',
    },
    {
      id: 'tech', tags: ['G'], title: 'Tourist Spot 1 Booking',
      estimate: '$32', detail: 'The Tech Interactive · Sat 1:00 PM entry',
      provider: 'thetech.org', done: true,
    },
    {
      id: 'winchester', tags: ['H'], title: 'Tourist Spot 2 Booking',
      estimate: '$46', detail: 'Winchester Mystery House · Sat 4:00 PM tour',
      provider: 'winchestermysteryhouse.com',
    },
  ],
}

export const allTags = new Set(trip.days.flatMap((d) => d.items.map((i) => i.tag)))

export const initialMessages: ChatMessage[] = [
  { id: 'm1', role: 'assistant', text: 'Hi, where do you want to go?' },
  { id: 'm2', role: 'user', text: 'San Jose, CA' },
  { id: 'm3', role: 'assistant', text: 'Cool, where are you travelling from?' },
  { id: 'm4', role: 'user', text: 'College Station' },
  { id: 'm5', role: 'assistant', text: 'Nice. When are you going, and what are you into? Food, outdoors, museums, nightlife…' },
  { id: 'm6', role: 'user', text: 'first weekend of march, mostly tech stuff and good food. maybe some gardens' },
  { id: 'm7', role: 'assistant', text: 'Alright, I will generate a plan. Gimme a sec.' },
  { id: 's1', role: 'status', text: 'Checked weather for San Jose · Mar 5–7' },
  { id: 's2', role: 'status', text: 'Found 12 hotels under $150/night' },
  { id: 'v1', role: 'version', text: 'Plan created · v1' },
  { id: 'm8', role: 'assistant', text: 'Here’s a 3-day plan. Tap any letter to see it on the map, or refer to it here — e.g. “replace H with something outdoors”.' },
  { id: 'm9', role: 'user', text: 'I like the plan, please change F to something vegan' },
  { id: 's3', role: 'status', text: 'Searching vegan restaurants near downtown' },
  { id: 'v2', role: 'version', text: 'Plan updated · v2' },
  { id: 'm10', role: 'assistant', text: 'Done — replaced F (Baconhouse) with Good Karma Kitchen, a vegan brunch spot 5 min from D. I also saved “vegan” to your profile for future trips.' },
]
