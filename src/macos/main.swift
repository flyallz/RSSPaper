import AppKit
import SwiftUI
import Foundation
import Security
import CryptoKit

struct Journal: Sendable {
    let name: String
    let url: URL
    let isRequired: Bool
    let isChinese: Bool
}

struct FeedRecord: Codable, Identifiable, Sendable, Equatable {
    var id: UUID = UUID()
    var name: String
    var urlString: String
    var isRequired: Bool
    var isChinese: Bool
    var journal: Journal? {
        guard let url = URL(string: urlString), ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil else { return nil }
        return Journal(name: name, url: url, isRequired: isRequired, isChinese: isChinese)
    }
}

struct LLMSettings: Codable, Equatable {
    var enabled = false
    var endpoint = ""
    var model = ""
}

enum LLMRequestError: LocalizedError {
    case http(Int, String)
    case invalidResponse
    case emptyContent(String)

    var errorDescription: String? {
        switch self {
        case let .http(status, detail):
            let hint: String
            switch status {
            case 400: hint = "请求参数错误"
            case 401, 403: hint = "密钥无效或无权调用"
            case 402: hint = "账户余额或额度不足"
            case 404: hint = "接口地址或模型不存在"
            case 422: hint = "请求参数不被接口接受"
            case 429: hint = "调用过于频繁或额度受限"
            case 500...599: hint = "接口服务暂时出错"
            default: hint = "接口请求失败"
            }
            return "HTTP \(status)：\(detail.isEmpty ? hint : detail)"
        case .invalidResponse: return "接口返回内容无法识别，请确认它兼容 Chat Completions。"
        case let .emptyContent(reason):
            return reason == "length" ? "模型输出达到上限，未返回译题。" : "模型没有返回译题。"
        }
    }
}

enum UserFiles {
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let url = base.appendingPathComponent("EdTechRadar", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
    static func read<T: Decodable>(_ name: String, as type: T.Type) -> T? {
        guard let data = try? Data(contentsOf: directory.appendingPathComponent(name)) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }
    static func write<T: Encodable>(_ value: T, to name: String) {
        guard let data = try? JSONEncoder().encode(value) else { return }
        try? data.write(to: directory.appendingPathComponent(name), options: .atomic)
    }
}

enum APIKeychain {
    static let service = "local.codex.edtechradar.llm"
    static let account = "api-key"
    static func read() -> String {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
    static func save(_ key: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
        if !key.isEmpty {
            var item = query
            item[kSecValueData as String] = Data(key.utf8)
            SecItemAdd(item as CFDictionary, nil)
        }
    }
}

struct Paper: Identifiable, Sendable {
    let id: String
    let title: String
    let link: URL
    let journal: String
    let date: Date?
    let isRequired: Bool
    let isChinese: Bool
}

final class OPMLReader: NSObject, XMLParserDelegate {
    private(set) var journals: [Journal] = []
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes: [String: String] = [:]) {
        guard elementName == "outline", let raw = attributes["xmlUrl"], let url = URL(string: raw) else { return }
        var name = attributes["title"] ?? attributes["text"] ?? "期刊"
        let required = name.hasPrefix("[必读]")
        name = name.replacingOccurrences(of: "[必读] ", with: "").replacingOccurrences(of: "[选读] ", with: "")
        let cnki = url.host == "rss.cnki.net"
        journals.append(Journal(name: name, url: url, isRequired: required, isChinese: cnki))
    }
}

final class RSSReader: NSObject, XMLParserDelegate {
    private let journal: Journal
    private(set) var papers: [Paper] = []
    private var inItem = false
    private var field = ""
    private var value = ""
    private var itemTitle = ""
    private var itemLink = ""
    private var itemDate = ""
    init(journal: Journal) { self.journal = journal }
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes: [String: String] = [:]) {
        let e = elementName.lowercased()
        if e == "item" || e == "entry" {
            inItem = true; itemTitle = ""; itemLink = ""; itemDate = ""
        } else if inItem {
            field = e; value = ""
            if e == "link", let href = attributes["href"] { itemLink = href }
        }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) { if inItem { value += string } }
    func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) { if inItem { value += String(data: CDATABlock, encoding: .utf8) ?? "" } }
    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
        let e = elementName.lowercased()
        if e == "item" || e == "entry" {
            let title = itemTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let raw = itemLink.trimmingCharacters(in: .whitespacesAndNewlines)
            if !title.isEmpty, let link = URL(string: raw), ["http", "https"].contains(link.scheme?.lowercased() ?? "") {
                let id = journal.name + "|" + (link.host ?? "") + "|" + raw
                papers.append(Paper(id: id, title: title, link: link, journal: journal.name, date: DateParser.parse(itemDate), isRequired: journal.isRequired, isChinese: journal.isChinese))
            }
            inItem = false; field = ""; value = ""
        } else if inItem && e == field {
            let v = value.trimmingCharacters(in: .whitespacesAndNewlines)
            switch e {
            case "title": itemTitle = v
            case "link": if itemLink.isEmpty { itemLink = v }
            case "pubdate", "date", "published", "updated": if itemDate.isEmpty { itemDate = v }
            default: break
            }
            field = ""; value = ""
        }
    }
}

enum DateParser {
    static func parse(_ raw: String) -> Date? {
        let r = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if r.isEmpty { return nil }
        let forms = ["EEE, dd MMM yyyy HH:mm:ss Z", "EEE, d MMM yyyy HH:mm:ss Z", "yyyy-MM-dd'T'HH:mm:ssXXXXX", "yyyy-MM-dd'T'HH:mm:ssZ", "yyyy-MM-dd", "yyyy/MM/dd HH:mm:ss"]
        for pattern in forms {
            let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = TimeZone(secondsFromGMT: 0); f.dateFormat = pattern
            if let date = f.date(from: r) { return date }
        }
        return ISO8601DateFormatter().date(from: r)
    }
}

@MainActor final class RadarStore: ObservableObject {
    @Published var papers: [Paper] = []
    @Published var feeds: [FeedRecord] = []
    @Published var llm = LLMSettings()
    @Published var translations: [String: String] = [:]
    @Published var translationErrors: [String: String] = [:]
    @Published var isLoading = false
    @Published var lastUpdate: Date? = nil
    @Published var succeeded = 0
    @Published var failed = 0
    @Published var message = "正在连接期刊…"
    private var defaultFeeds: [FeedRecord] = []
    private var queued: [(String, String)] = []
    private var pending: Set<String> = []
    private var activeTranslations = 0
    private var needsRefresh = false
    init() {
        if let url = Bundle.main.url(forResource: "edtech-radar", withExtension: "opml"), let data = try? Data(contentsOf: url) {
            let reader = OPMLReader(); let parser = XMLParser(data: data); parser.delegate = reader
            if parser.parse() {
                defaultFeeds = reader.journals.map { FeedRecord(name: $0.name, urlString: $0.url.absoluteString, isRequired: $0.isRequired, isChinese: $0.isChinese) }
            }
        }
        feeds = UserFiles.read("feeds.json", as: [FeedRecord].self) ?? defaultFeeds
        llm = UserFiles.read("llm-settings.json", as: LLMSettings.self) ?? LLMSettings()
        translations = UserFiles.read("translations.json", as: [String: String].self) ?? [:]
        if feeds.isEmpty { message = "请到设置中添加 RSS 订阅。" }
    }
    func saveFeed(_ feed: FeedRecord) -> String? {
        let name = feed.name.trimmingCharacters(in: .whitespacesAndNewlines)
        let address = feed.urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        var clean = feed; clean.name = name; clean.urlString = address
        guard !name.isEmpty else { return "请填写期刊名称。" }
        guard clean.journal != nil else { return "请输入完整的 http:// 或 https:// RSS 地址。" }
        guard !feeds.contains(where: { $0.id != clean.id && $0.urlString.caseInsensitiveCompare(address) == .orderedSame }) else { return "这个 RSS 地址已在订阅列表中。" }
        if let index = feeds.firstIndex(where: { $0.id == clean.id }) { feeds[index] = clean }
        else { feeds.append(clean) }
        UserFiles.write(feeds, to: "feeds.json")
        refresh()
        return nil
    }
    func deleteFeed(_ id: UUID) {
        feeds.removeAll { $0.id == id }
        UserFiles.write(feeds, to: "feeds.json")
        papers.removeAll { p in !feeds.contains(where: { $0.name == p.journal }) }
        refresh()
    }
    func resetFeeds() {
        feeds = defaultFeeds
        UserFiles.write(feeds, to: "feeds.json")
        refresh()
    }
    func saveLLM(_ settings: LLMSettings, key: String) -> String? {
        let endpoint = settings.endpoint.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = settings.model.trimmingCharacters(in: .whitespacesAndNewlines)
        if settings.enabled {
            guard validEndpoint(endpoint) else { return "接口地址需为 HTTPS，或本机 HTTP 地址。" }
            guard !model.isEmpty else { return "请填写模型名称。" }
        }
        llm = LLMSettings(enabled: settings.enabled, endpoint: endpoint, model: model)
        UserFiles.write(llm, to: "llm-settings.json")
        APIKeychain.save(key.trimmingCharacters(in: .whitespacesAndNewlines))
        queued.removeAll(); pending.removeAll()
        translationErrors.removeAll()
        return nil
    }
    func validEndpoint(_ raw: String) -> Bool {
        guard let url = URL(string: raw), let host = url.host, !host.isEmpty else { return false }
        if url.scheme?.lowercased() == "https" { return true }
        return url.scheme?.lowercased() == "http" && ["localhost", "127.0.0.1", "::1"].contains(host)
    }
    private func translationID(_ title: String) -> String {
        let input = llm.endpoint + "|" + llm.model + "|" + title
        return SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    func translatedTitle(for paper: Paper) -> String? { llm.enabled ? translations[translationID(paper.title)] : nil }
    func translationError(for paper: Paper) -> String? { llm.enabled ? translationErrors[translationID(paper.title)] : nil }
    func requestTranslation(for paper: Paper) {
        guard !paper.isChinese, llm.enabled else { return }
        let id = translationID(paper.title)
        guard translations[id] == nil, translationErrors[id] == nil, !pending.contains(id) else { return }
        pending.insert(id); queued.append((id, paper.title)); pumpTranslations()
    }
    private func pumpTranslations() {
        guard llm.enabled else { return }
        while activeTranslations < 2 && !queued.isEmpty {
            let (id, title) = queued.removeFirst()
            activeTranslations += 1
            let settings = llm
            let key = APIKeychain.read()
            Task {
                do {
                    let result = try await Self.translate(title, settings: settings, key: key)
                    if settings == llm { translations[id] = result; UserFiles.write(translations, to: "translations.json") }
                } catch {
                    if settings == llm { translationErrors[id] = "翻译失败：\(Self.errorSummary(error))，点击重试" }
                }
                pending.remove(id); activeTranslations = max(0, activeTranslations - 1); pumpTranslations()
            }
        }
    }
    func retryTranslation(for paper: Paper) {
        translationErrors.removeValue(forKey: translationID(paper.title))
        requestTranslation(for: paper)
    }
    static func errorSummary(_ error: Error) -> String {
        if let issue = error as? LLMRequestError { return issue.localizedDescription }
        if let issue = error as? URLError {
            switch issue.code {
            case .timedOut: return "连接超时"
            case .notConnectedToInternet, .networkConnectionLost: return "网络连接中断"
            case .cannotFindHost, .cannotConnectToHost: return "无法连接接口服务器"
            case .secureConnectionFailed, .serverCertificateUntrusted: return "安全连接失败"
            default: return issue.localizedDescription
            }
        }
        return error.localizedDescription
    }
    static func translate(_ title: String, settings: LLMSettings, key: String) async throws -> String {
        guard let url = URL(string: settings.endpoint) else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"; request.timeoutInterval = 45
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !key.isEmpty { request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization") }
        var body: [String: Any] = ["model": settings.model, "temperature": 0, "max_tokens": 256,
            "messages": [["role": "system", "content": "将英文教育技术学术论文标题准确翻译成简体中文。只返回中文译题，不加引号、注释或原文。"], ["role": "user", "content": title]]]
        if url.host?.lowercased() == "api.deepseek.com" { body["thinking"] = ["type": "disabled"] }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw LLMRequestError.invalidResponse }
        if !(200..<300).contains(http.statusCode) {
            let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            let issue = payload?["error"] as? [String: Any]
            var detail = (issue?["message"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !key.isEmpty { detail = detail.replacingOccurrences(of: key, with: "[密钥已隐藏]") }
            detail = detail.replacingOccurrences(of: #"(?i)sk-[A-Za-z0-9_-]{8,}"#, with: "[密钥已隐藏]", options: .regularExpression)
            if detail.count > 180 { detail = String(detail.prefix(180)) + "…" }
            throw LLMRequestError.http(http.statusCode, detail)
        }
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let choices = json?["choices"] as? [[String: Any]]
        let message = choices?.first?["message"] as? [String: Any]
        guard let result = (message?["content"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !result.isEmpty else {
            throw choices == nil ? LLMRequestError.invalidResponse : LLMRequestError.emptyContent(choices?.first?["finish_reason"] as? String ?? "")
        }
        return result
    }
    func refresh() {
        if isLoading { needsRefresh = true; return }
        guard !feeds.isEmpty else { papers = []; message = "请到设置中添加 RSS 订阅。"; return }
        let list = feeds.compactMap(\.journal)
        isLoading = true; message = "正在更新 \(list.count) 本期刊…"
        Task {
            var all: [Paper] = []
            var ok = 0
            var bad = 0
            await withTaskGroup(of: [Paper]?.self) { group in
                for journal in list {
                    group.addTask {
                        var request = URLRequest(url: journal.url)
                        request.timeoutInterval = 24
                        request.setValue("教育技术期刊雷达/1.0", forHTTPHeaderField: "User-Agent")
                        do {
                            let (data, response) = try await URLSession.shared.data(for: request)
                            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return nil }
                            let reader = RSSReader(journal: journal)
                            let parser = XMLParser(data: data); parser.delegate = reader
                            guard parser.parse(), !reader.papers.isEmpty else { return nil }
                            return reader.papers
                        } catch { return nil }
                    }
                }
                for await result in group {
                    if let result { ok += 1; all += result } else { bad += 1 }
                }
            }
            // The same item can appear again when a publisher changes its issue metadata.
            var unique: [String: Paper] = [:]
            for p in all { unique[p.id] = p }
            let sorted = unique.values.sorted {
                let a = $0.date ?? .distantPast, b = $1.date ?? .distantPast
                if a != b { return a > b }
                return $0.title.localizedCompare($1.title) == .orderedAscending
            }
            papers = sorted; succeeded = ok; failed = bad; lastUpdate = Date(); isLoading = false
            message = ok == 0 ? "暂时无法读取 RSS，请检查网络后重试。" : bad == 0 ? "已更新 \(ok) 本期刊" : "已更新 \(ok) 本，\(bad) 本暂不可用"
            if needsRefresh { needsRefresh = false; refresh() }
        }
    }
}

struct RadarView: View {
    @StateObject private var store = RadarStore()
    @State private var choice = 0
    @State private var language = 0
    @State private var showSettings = false
    private let background = Color(red: 0.965, green: 0.975, blue: 0.985)
    private var visible: [Paper] {
        store.papers.filter { p in
            (choice == 0 || (choice == 1 && p.isRequired) || (choice == 2 && !p.isRequired)) &&
            (language == 0 || (language == 1 && p.isChinese) || (language == 2 && !p.isChinese))
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("教育技术期刊雷达").font(.system(size: 21, weight: .bold, design: .rounded))
                    Text("培养方案 · \(store.feeds.count) 本 RSS").font(.system(size: 12)).foregroundColor(.secondary)
                }
                Spacer()
                Button { showSettings = true } label: {
                    Image(systemName: "gearshape").font(.system(size: 14, weight: .semibold)).frame(width: 32, height: 32)
                }.buttonStyle(.borderless).help("订阅与翻译设置")
                Button { store.refresh() } label: {
                    Image(systemName: "arrow.clockwise").font(.system(size: 14, weight: .semibold)).frame(width: 32, height: 32)
                }.buttonStyle(.borderless).help("立即刷新").disabled(store.isLoading)
            }.padding(.top, 26)
            HStack(spacing: 7) {
                Circle().fill(store.isLoading ? Color.orange : (store.failed == 0 && store.succeeded > 0 ? Color.green : Color.orange)).frame(width: 7, height: 7)
                Text(store.message).font(.system(size: 11)).foregroundColor(.secondary).lineLimit(1)
                Spacer()
                if let date = store.lastUpdate { Text(date, style: .time).font(.system(size: 11)).foregroundColor(.secondary) }
            }.padding(.top, 11)
            if store.isLoading { ProgressView().progressViewStyle(.linear).padding(.top, 8) }
            Picker("阅读要求", selection: $choice) {
                Text("全部").tag(0); Text("必读").tag(1); Text("选读").tag(2)
            }.pickerStyle(.segmented).labelsHidden().padding(.top, 16)
            Picker("语言", selection: $language) {
                Text("中英").tag(0); Text("中文").tag(1); Text("英文").tag(2)
            }.pickerStyle(.segmented).labelsHidden().padding(.top, 8)
            HStack {
                Text("近期论文").font(.system(size: 13, weight: .semibold))
                Spacer()
                Text("\(visible.count) 条").font(.system(size: 11)).foregroundColor(.secondary)
            }.padding(.top, 17).padding(.bottom, 7)
            Divider()
            ScrollView {
                LazyVStack(spacing: 0) {
                    if visible.isEmpty {
                        VStack(spacing: 9) {
                            Image(systemName: "text.book.closed").font(.system(size: 25)).foregroundColor(.secondary)
                            Text(store.isLoading ? "正在获取新论文…" : "暂无可显示的论文").font(.system(size: 13)).foregroundColor(.secondary)
                        }.frame(maxWidth: .infinity).padding(.top, 70)
                    }
                    ForEach(visible) { p in
                        VStack(alignment: .leading, spacing: 5) {
                            Button { NSWorkspace.shared.open(p.link) } label: {
                                VStack(alignment: .leading, spacing: 5) {
                                Text(p.title).font(.system(size: 13, weight: .medium)).foregroundColor(.primary).lineLimit(3).multilineTextAlignment(.leading)
                                if let translated = store.translatedTitle(for: p), !p.isChinese {
                                    Text(translated).font(.system(size: 12)).foregroundColor(Color(red: 0.16, green: 0.36, blue: 0.51)).lineLimit(3).multilineTextAlignment(.leading)
                                }
                                HStack(spacing: 5) {
                                    Text(p.isRequired ? "必读" : "选读").font(.system(size: 10, weight: .semibold)).foregroundColor(p.isRequired ? Color(red: 0.05, green: 0.40, blue: 0.63) : .secondary)
                                    Text("·").foregroundColor(.secondary)
                                    Text(p.journal).lineLimit(1)
                                    Spacer(minLength: 2)
                                    if let date = p.date { Text(date, format: .dateTime.month(.twoDigits).day(.twoDigits)) }
                                }.font(.system(size: 10)).foregroundColor(.secondary)
                                }.frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
                            }.buttonStyle(.plain)
                            if let error = store.translationError(for: p), !p.isChinese {
                                Button(error) { store.retryTranslation(for: p) }.font(.system(size: 11)).foregroundColor(.orange).buttonStyle(.plain)
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 11).onAppear { store.requestTranslation(for: p) }
                        Divider()
                    }
                }
            }
            HStack {
                Text("每 30 分钟自动刷新").font(.system(size: 10)).foregroundColor(.secondary)
                Spacer()
                Text("点击标题打开原文").font(.system(size: 10)).foregroundColor(.secondary)
            }.padding(.top, 9).padding(.bottom, 3)
        }
        .padding(.horizontal, 18)
        .background(background)
        .frame(minWidth: 350, idealWidth: 400, maxWidth: 540, minHeight: 430, idealHeight: 565)
        .onAppear { store.refresh() }
        .onChange(of: store.llm) { _, newValue in
            if newValue.enabled { for paper in visible.prefix(20) { store.requestTranslation(for: paper) } }
        }
        .sheet(isPresented: $showSettings) { SettingsView(store: store) }
        .onReceive(Timer.publish(every: 1800, on: .main, in: .common).autoconnect()) { _ in store.refresh() }
    }
}

struct SettingsView: View {
    @ObservedObject var store: RadarStore
    @Environment(\.dismiss) private var dismiss
    @State private var tab = 0
    @State private var selected: UUID?
    @State private var draft = FeedRecord(name: "", urlString: "", isRequired: false, isChinese: false)
    @State private var feedStatus = "选择期刊修改，或添加新的 RSS。"
    @State private var settings = LLMSettings()
    @State private var apiKey = ""
    @State private var llmStatus = "只会将英文论文标题发送到你填写的接口。"
    @State private var testing = false
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Text("期刊雷达设置").font(.system(size: 20, weight: .bold))
                Spacer()
                Button("完成") { dismiss() }
            }
            Picker("设置", selection: $tab) {
                Text("RSS 订阅").tag(0)
                Text("大模型翻译").tag(1)
            }.pickerStyle(.segmented).labelsHidden()
            if tab == 0 { feedPane } else { llmPane }
        }
        .padding(22).frame(width: 640, height: 500)
        .onAppear { settings = store.llm; apiKey = APIKeychain.read() }
    }
    private var feedPane: some View {
        HStack(alignment: .top, spacing: 15) {
            VStack(alignment: .leading, spacing: 8) {
                Text("订阅列表（\(store.feeds.count)）").font(.system(size: 12, weight: .semibold))
                List(selection: $selected) {
                    ForEach(store.feeds) { feed in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(feed.name).font(.system(size: 12, weight: .medium))
                            Text(feed.isRequired ? "必读" : "选读").font(.system(size: 10)).foregroundColor(.secondary)
                        }.tag(feed.id)
                    }
                }.onChange(of: selected) { _, newValue in
                    if let feed = store.feeds.first(where: { $0.id == newValue }) { draft = feed }
                }
                HStack {
                    Button("新增") { selected = nil; draft = FeedRecord(name: "", urlString: "", isRequired: false, isChinese: false); feedStatus = "填写新期刊资料后保存。" }
                    Button("删除") {
                        if let id = selected {
                            store.deleteFeed(id); selected = nil
                            draft = FeedRecord(name: "", urlString: "", isRequired: false, isChinese: false)
                            feedStatus = "已删除订阅。"
                        }
                    }.disabled(selected == nil)
                }
            }.frame(width: 215)
            VStack(alignment: .leading, spacing: 11) {
                Text(selected == nil ? "添加 RSS" : "修改 RSS").font(.system(size: 14, weight: .semibold))
                TextField("期刊名称", text: $draft.name)
                TextField("https://… RSS 地址", text: $draft.urlString)
                Toggle("培养方案必读", isOn: $draft.isRequired)
                Toggle("中文期刊", isOn: $draft.isChinese)
                Text("RSS 地址会保存在本机；保存后立即重新抓取。")
                    .font(.system(size: 11)).foregroundColor(.secondary)
                HStack {
                    Button("保存订阅") {
                        if let error = store.saveFeed(draft) { feedStatus = error }
                        else { selected = draft.id; feedStatus = "已保存，正在更新。" }
                    }.buttonStyle(.borderedProminent)
                    Button("恢复预置 20 本") {
                        store.resetFeeds(); selected = nil
                        draft = FeedRecord(name: "", urlString: "", isRequired: false, isChinese: false)
                        feedStatus = "已恢复预置订阅。"
                    }
                }
                Text(feedStatus).font(.system(size: 11)).foregroundColor(.secondary)
                Spacer()
            }.textFieldStyle(.roundedBorder)
        }
    }
    private var llmPane: some View {
        VStack(alignment: .leading, spacing: 12) {
            Toggle("启用英文标题中文翻译", isOn: $settings.enabled)
                .font(.system(size: 13, weight: .medium))
            Text("接口地址（兼容 OpenAI Chat Completions 的完整地址）").font(.system(size: 12))
            TextField("https://…/v1/chat/completions", text: $settings.endpoint).textFieldStyle(.roundedBorder)
            Text("模型名称").font(.system(size: 12))
            TextField("例如：你使用的模型 ID", text: $settings.model).textFieldStyle(.roundedBorder)
            Text("API 密钥（本机钥匙串保存；本地模型可以留空）").font(.system(size: 12))
            SecureField("API Key", text: $apiKey).textFieldStyle(.roundedBorder)
            Text("翻译只针对显示在卡片中的英文标题。原文保留，中文译题显示在下一行；结果会缓存，接口可能产生费用。")
                .font(.system(size: 11)).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("保存配置") {
                    llmStatus = store.saveLLM(settings, key: apiKey) ?? "配置已保存。"
                }.buttonStyle(.borderedProminent)
                Button(testing ? "正在测试…" : "测试接口") {
                    testing = true
                    Task {
                        let candidate = LLMSettings(enabled: true, endpoint: settings.endpoint.trimmingCharacters(in: .whitespacesAndNewlines), model: settings.model.trimmingCharacters(in: .whitespacesAndNewlines))
                        guard store.validEndpoint(candidate.endpoint), !candidate.model.isEmpty else { llmStatus = "请填写 HTTPS 或本机 HTTP 接口地址及模型名称。"; testing = false; return }
                        do { llmStatus = "测试成功：" + (try await RadarStore.translate("Learning with technology", settings: candidate, key: apiKey)) }
                        catch { llmStatus = "测试失败：" + RadarStore.errorSummary(error) }
                        testing = false
                    }
                }.disabled(testing)
            }
            Text(llmStatus).font(.system(size: 11)).foregroundColor(.secondary).lineLimit(4).textSelection(.enabled)
            Spacer()
        }
    }
}

final class RadarDelegate: NSObject, NSApplicationDelegate {
    var window: NSPanel?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 400, height: 565), styleMask: [.titled, .closable, .miniaturizable, .resizable, .utilityWindow], backing: .buffered, defer: false)
        panel.title = "教育技术期刊雷达"
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isReleasedWhenClosed = false
        panel.minSize = NSSize(width: 350, height: 430)
        panel.contentView = NSHostingView(rootView: RadarView())
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        window = panel
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu(title: "教育技术期刊雷达")
        appMenu.addItem(withTitle: "退出期刊雷达", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)

        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApp.mainMenu = menu
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

#if !RADAR_TEST
@main struct RadarMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = RadarDelegate()
        app.delegate = delegate
        app.run()
    }
}
#endif
