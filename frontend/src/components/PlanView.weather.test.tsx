// Step 31: day weather chips ("avg" for climate), the header summary chip and the Open-Meteo credit.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { sanJoseProfile, sanJoseV2 } from '@/fixtures'
import type { DayWeather, Itinerary } from '@/types'
import { PlanView } from './PlanView'

const forecast: DayWeather = { high_f: 66.4, low_f: 47.6, condition: 'sunny', icon: '☀️', source: 'forecast' }
const climate: DayWeather = { high_f: 70, low_f: 52, condition: 'cloudy', icon: '☁️', source: 'climate' }

// sanJoseV2 with each day's weather replaced (in day order) and the summary set.
function withWeather(days: (DayWeather | null)[], summary: string | null): Itinerary {
  return {
    ...sanJoseV2,
    weather_summary: summary,
    days: sanJoseV2.days.map((d, i) => ({ ...d, weather: days[i] ?? null })),
  }
}

function renderPlan(itinerary: Itinerary) {
  return render(<PlanView itinerary={itinerary} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
}

const credit = () => screen.queryByRole('link', { name: 'Weather data by Open-Meteo.com' })

describe('PlanView weather chips', () => {
  it('renders a forecast chip with icon and rounded high / low, without "avg"', () => {
    renderPlan(withWeather([forecast], null))
    const chips = screen.getAllByTestId('weather-chip')
    expect(chips).toHaveLength(1)
    expect(chips[0].textContent).toContain('☀️')
    expect(chips[0].textContent).toContain('66° / 48°')
    expect(chips[0].textContent).not.toMatch(/avg/)
  })

  it('labels a climate-average day "avg"', () => {
    renderPlan(withWeather([forecast, climate], null))
    const chips = screen.getAllByTestId('weather-chip')
    expect(chips).toHaveLength(2)
    expect(chips[1].textContent).toContain('70° / 52°')
    expect(chips[1].textContent).toMatch(/avg/)
    expect(screen.getAllByText('avg')).toHaveLength(1)
  })

  it('hides the chip on a day whose weather is null', () => {
    renderPlan(withWeather([null, forecast], null))
    const chips = screen.getAllByTestId('weather-chip')
    expect(chips).toHaveLength(1)
    const day1 = screen.getAllByRole('heading', { level: 2 })[0].closest('section')
    expect(day1?.querySelector('[data-testid="weather-chip"]')).toBeNull()
  })

  it('shows no chips when no day has weather', () => {
    renderPlan(withWeather([], null))
    expect(screen.queryByTestId('weather-chip')).toBeNull()
  })
})

describe('PlanView weather summary chip', () => {
  it('shows the summary with the first weather icon', () => {
    renderPlan(withWeather([null, climate], 'Mild and cloudy, 52–70 °F'))
    const summary = screen.getByTestId('weather-summary')
    expect(summary.textContent).toContain('Mild and cloudy, 52–70 °F')
    expect(summary.textContent).toContain('☁️')
  })

  it('is hidden when weather_summary is null', () => {
    renderPlan(withWeather([forecast], null))
    expect(screen.queryByTestId('weather-summary')).toBeNull()
  })
})

describe('PlanView Open-Meteo credit', () => {
  it('links to open-meteo.com when the plan has weather', () => {
    renderPlan(withWeather([forecast], 'Sunny, 48–66 °F'))
    expect(credit()?.getAttribute('href')).toMatch(/^https:\/\/open-meteo\.com/)
  })

  it('shows when only days have weather (no summary)', () => {
    renderPlan(withWeather([forecast], null))
    expect(credit()).toBeTruthy()
  })

  it('is hidden when the plan has no weather at all (tool failed)', () => {
    renderPlan(withWeather([], null))
    expect(credit()).toBeNull()
  })
})
