import { describe, expect, it } from 'vitest'
import { fixtureGame } from '../src/api/mockBridge'
import { filterGames } from '../src/features/library/libraryFilters'

describe('library filters', () => {
  it('matches title case-insensitively and combines status and engine filters', () => {
    const games = [
      fixtureGame({ id: '1', title: 'Alice', status: 'installed', engineId: 'renpy' }),
      fixtureGame({ id: '2', title: 'Bob', status: 'missing', engineId: 'unity' }),
    ]

    expect(filterGames(games, {
      query: 'ALI', status: 'installed', engine: 'renpy',
    }).map((game) => game.id)).toEqual(['1'])
  })

  it('matches version case-insensitively and tolerates games without one', () => {
    const games = [
      fixtureGame({ id: '1', title: 'AoiChan', version: 'v1.0.8' }),
      fixtureGame({ id: '2', title: 'Alice', version: 'Build 2048' }),
      fixtureGame({ id: '3', title: 'No Version', version: null }),
    ]

    expect(filterGames(games, {
      query: '1.0.8', status: 'all', engine: 'all',
    }).map((game) => game.id)).toEqual(['1'])
    expect(filterGames(games, {
      query: 'BUILD', status: 'all', engine: 'all',
    }).map((game) => game.id)).toEqual(['2'])
    expect(filterGames(games, {
      query: 'missing', status: 'all', engine: 'all',
    })).toEqual([])
  })
})
