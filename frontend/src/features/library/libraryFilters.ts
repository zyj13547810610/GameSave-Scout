import type { Game, GroupFilter } from '../../api/contracts'

export type LibraryFilter = {
  query: string
  status: 'all' | Game['status']
  engine: 'all' | string
  group: GroupFilter
}

export function filterGames(games: Game[], filter: LibraryFilter): Game[] {
  const query = filter.query.trim().toLocaleLowerCase()
  return games.filter((game) => {
    const matchesQuery = game.title.toLocaleLowerCase().includes(query)
      || (game.version ?? '').toLocaleLowerCase().includes(query)
    if (query && !matchesQuery) return false
    if (filter.status !== 'all' && game.status !== filter.status) return false
    if (filter.engine !== 'all' && game.engineId !== filter.engine) return false
    if (filter.group === 'ungrouped' && game.groupIds.length !== 0) return false
    if (
      filter.group !== 'all'
      && filter.group !== 'ungrouped'
      && !game.groupIds.includes(filter.group)
    ) return false
    return true
  })
}
