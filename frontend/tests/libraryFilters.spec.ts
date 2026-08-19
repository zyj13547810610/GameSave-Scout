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
      query: 'ALI', status: 'installed', engine: 'renpy', group: 'all',
    }).map((game) => game.id)).toEqual(['1'])
  })

  it('matches version case-insensitively and tolerates games without one', () => {
    const games = [
      fixtureGame({ id: '1', title: 'AoiChan', version: 'v1.0.8' }),
      fixtureGame({ id: '2', title: 'Alice', version: 'Build 2048' }),
      fixtureGame({ id: '3', title: 'No Version', version: null }),
    ]

    expect(filterGames(games, {
      query: '1.0.8', status: 'all', engine: 'all', group: 'all',
    }).map((game) => game.id)).toEqual(['1'])
    expect(filterGames(games, {
      query: 'BUILD', status: 'all', engine: 'all', group: 'all',
    }).map((game) => game.id)).toEqual(['2'])
    expect(filterGames(games, {
      query: 'missing', status: 'all', engine: 'all', group: 'all',
    })).toEqual([])
  })

  it('filters ungrouped games and intersects a concrete group with all filters', () => {
    const games = [
      fixtureGame({
        id: 'summer', title: '夏日口袋', status: 'installed',
        engineId: 'siglus', groupIds: ['group-rpg'],
      }),
      fixtureGame({ id: 'other', title: 'Other', groupIds: [] }),
    ]

    expect(filterGames(games, {
      query: '', status: 'all', engine: 'all', group: 'ungrouped',
    }).map((game) => game.id)).toEqual(['other'])
    expect(filterGames(games, {
      query: '夏', status: 'installed', engine: 'siglus', group: 'group-rpg',
    }).map((game) => game.id)).toEqual(['summer'])
    expect(filterGames(games, {
      query: '夏', status: 'missing', engine: 'siglus', group: 'group-rpg',
    })).toEqual([])
  })
})
