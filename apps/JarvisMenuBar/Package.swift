// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "JarvisMenuBar",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "JarvisMenuBar", targets: ["JarvisMenuBar"])
    ],
    targets: [
        .executableTarget(
            name: "JarvisMenuBar",
            path: "Sources"
        )
    ]
)
