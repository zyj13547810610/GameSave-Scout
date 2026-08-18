import type { Game } from '../../api/contracts'

export type LibraryFilter = {
  query: string
  status: 'all' | Game['status']
  engine: 'all' | string
}

export function filterGames(games: Game[], filter: LibraryFilter): Game[] {
  const query = filter.query.trim().toLocaleLowerCase()
  return games.filter((game) => {
    const matchesQuery = game.title.toLocaleLowerCase().includes(query)
      || (game.version ?? '').toLocaleLowerCase().includes(query)
    if (query && !matchesQuery) return false
    if (filter.status !== 'all' && game.status !== filter.status) return false
    if (filter.engine !== 'all' && game.engineId !== filter.engine) return false
    return true
  })
}
