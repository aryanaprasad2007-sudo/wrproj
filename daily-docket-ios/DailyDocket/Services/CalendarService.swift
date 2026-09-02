import Foundation

/// Fetches every enabled calendar's ICS feed directly — no same-origin proxy
/// needed like the web app requires, because native networking isn't subject
/// to browser CORS. Falls back to the last good copy on disk when a feed is
/// unreachable, same "one dead feed can't take the others down" contract as
/// js/calendar.js's fetchAllFeeds().
struct FeedResult {
    var source: CalendarSource
    var text: String?
    var stale: Bool
    var error: String?
}

actor CalendarService {
    static let shared = CalendarService()

    private let cacheDir: URL

    init() {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        cacheDir = base.appendingPathComponent("docket-feeds", isDirectory: true)
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
    }

    private func cacheURL(for id: String) -> URL {
        cacheDir.appendingPathComponent("\(id).ics")
    }

    private func loadCache(_ id: String) -> String? {
        try? String(contentsOf: cacheURL(for: id), encoding: .utf8)
    }

    private func saveCache(_ id: String, _ text: String) {
        try? text.write(to: cacheURL(for: id), atomically: true, encoding: .utf8)
    }

    func fetchOne(_ source: CalendarSource) async -> FeedResult {
        guard !source.normalizedURL.isEmpty, let url = URL(string: source.normalizedURL) else {
            if let cached = loadCache(source.id) {
                return FeedResult(source: source, text: cached, stale: true, error: "no URL configured")
            }
            return FeedResult(source: source, text: nil, stale: true, error: "no URL configured")
        }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
        request.setValue("text/calendar, text/plain, */*", forHTTPHeaderField: "Accept")

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw URLError(.badServerResponse)
            }
            guard let text = String(data: data, encoding: .utf8),
                  text.prefix(2048).range(of: "BEGIN:VCALENDAR") != nil
            else {
                throw URLError(.cannotParseResponse)
            }
            saveCache(source.id, text)
            return FeedResult(source: source, text: text, stale: false, error: nil)
        } catch {
            if let cached = loadCache(source.id) {
                return FeedResult(source: source, text: cached, stale: true, error: error.localizedDescription)
            }
            return FeedResult(source: source, text: nil, stale: true, error: error.localizedDescription)
        }
    }

    func fetchAll(_ sources: [CalendarSource]) async -> [FeedResult] {
        let enabled = sources.filter(\.enabled)
        return await withTaskGroup(of: FeedResult.self) { group in
            for s in enabled { group.addTask { await self.fetchOne(s) } }
            var results: [FeedResult] = []
            for await r in group { results.append(r) }
            return results
        }
    }
}
