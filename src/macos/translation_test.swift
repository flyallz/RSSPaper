import Foundation
import AppKit

final class MockProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { request.url?.scheme == "mock" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var payload = request.httpBody ?? Data()
        if payload.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }
                payload.append(contentsOf: buffer.prefix(n))
            }
        }
        let body = (try? JSONSerialization.jsonObject(with: payload)) as? [String: Any]
        let messages = body?["messages"] as? [[String: Any]]
        assert(body?["model"] as? String == "deepseek-flash")
        assert(messages?.last?["content"] as? String == "Learning with technology")
        assert(request.value(forHTTPHeaderField: "Authorization") == "Bearer dummy")
        assert((body?["thinking"] as? [String: String])?["type"] == "disabled")
        let isError = request.url?.path == "/error"
        let data = Data((isError ? #"{"error":{"message":"Invalid API key"}}"# : #"{"choices":[{"message":{"content":"用技术学习"}}]}"#).utf8)
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: isError ? 401 : 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@main struct Test {
    static func main() async throws {
        URLProtocol.registerClass(MockProtocol.self)
        let good = LLMSettings(enabled: true, endpoint: "mock://api.deepseek.com/chat/completions", model: "deepseek-flash")
        let result = try await RadarStore.translate("Learning with technology", settings: good, key: "dummy")
        assert(result == "用技术学习")
        do {
            let bad = LLMSettings(enabled: true, endpoint: "mock://api.deepseek.com/error", model: "deepseek-flash")
            _ = try await RadarStore.translate("Learning with technology", settings: bad, key: "dummy")
            assertionFailure("expected HTTP error")
        } catch {
            let summary = RadarStore.errorSummary(error)
            assert(summary.contains("HTTP 401") && summary.contains("Invalid API key"))
        }
        print("DeepSeek request, translation parsing, and error detail: PASS")
    }
}
