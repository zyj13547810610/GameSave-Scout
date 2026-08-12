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
})
