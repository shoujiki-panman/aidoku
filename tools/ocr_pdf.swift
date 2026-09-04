// 画像PDF（本文のストリームが無いPDF）から、macOS の Vision で文字を読む。
//
// **なぜ要るか**: 虱潰しで読めない候補のうち3本が画像PDFだった。
// 本文が字ではなく絵として入っているので、PDFをいくら解析しても文字は出ない。
// 外部の変換器（anydoc）も `NeedsOcr` で降りる。**OCRしかない。**
//
// ★これは**開発時の道具**であって、作品本体ではない。
//   作品本体は Python 標準ライブラリのみで動く方針を変えない
//   （`plans/decisions/external-reader.md` と同じ線引き）。
//   macOS でしか動かないので、測定条件に混ぜてはいけない。
//
// ★**住民のAIは絵も読める。** ChatGPT や Claude は画像を見て答えられる。
//   うちの読み取り器が字しか扱えないだけなので、「読めない」を
//   「区が書いていない」に混ぜないための材料としてこれを使う。
//
// 追加のダウンロードは要らない（macOS 同梱の Vision / PDFKit）。
//
//   swiftc -O tools/ocr_pdf.swift -o /tmp/ocr_pdf
//   /tmp/ocr_pdf <PDFのパス>

import Foundation
import PDFKit
import Vision

// 1ページを描く大きさ。小さすぎると読めず、大きすぎると遅い。
let scale: CGFloat = 2.0

func render(page: PDFPage) -> CGImage? {
    let bounds = page.bounds(for: .mediaBox)
    let width = Int(bounds.width * scale)
    let height = Int(bounds.height * scale)
    guard width > 0, height > 0,
          let space = CGColorSpace(name: CGColorSpace.sRGB),
          let ctx = CGContext(data: nil, width: width, height: height,
                              bitsPerComponent: 8, bytesPerRow: 0,
                              space: space,
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
    else { return nil }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
    ctx.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

func recognize(_ image: CGImage) -> [String] {
    let request = VNRecognizeTextRequest()
    request.recognitionLanguages = ["ja-JP", "en-US"]
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    do {
        try handler.perform([request])
    } catch {
        FileHandle.standardError.write("認識できない: \(error)\n".data(using: .utf8)!)
        return []
    }
    let results = request.results ?? []
    return results.compactMap { $0.topCandidates(1).first?.string }
}

let args = CommandLine.arguments
guard args.count > 1 else {
    FileHandle.standardError.write("使い方: ocr_pdf <PDFのパス>\n".data(using: .utf8)!)
    exit(2)
}
guard let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("PDFとして開けない\n".data(using: .utf8)!)
    exit(1)
}

var lines: [String] = []
for index in 0..<doc.pageCount {
    guard let page = doc.page(at: index), let image = render(page: page) else { continue }
    lines.append(contentsOf: recognize(image))
}
print(lines.joined(separator: "\n"))
