// Node helper for tests/test_js_parity.py: analyzes a WAV file with the
// browser DSP engine (static/dsp.js) and prints the compact result as JSON.
"use strict";

const fs = require("fs");
const path = require("path");
const TruePeakDSP = require(path.join(__dirname, "..", "static", "dsp.js"));

function readWav(filePath) {
    const buf = fs.readFileSync(filePath);
    if (buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") {
        throw new Error("Not a WAV file");
    }
    let offset = 12;
    let fmt = null;
    let data = null;
    while (offset + 8 <= buf.length) {
        const id = buf.toString("ascii", offset, offset + 4);
        const size = buf.readUInt32LE(offset + 4);
        const body = offset + 8;
        if (id === "fmt ") {
            fmt = {
                format: buf.readUInt16LE(body),
                channels: buf.readUInt16LE(body + 2),
                sampleRate: buf.readUInt32LE(body + 4),
                bits: buf.readUInt16LE(body + 14),
            };
        } else if (id === "data") {
            data = buf.subarray(body, body + size);
        }
        offset = body + size + (size % 2);
    }
    if (!fmt || !data) throw new Error("Missing fmt/data chunk");
    const nFrames = Math.floor(data.length / (fmt.channels * (fmt.bits / 8)));
    const channels = [];
    for (let ch = 0; ch < fmt.channels; ch++) channels.push(new Float32Array(nFrames));
    for (let i = 0; i < nFrames; i++) {
        for (let ch = 0; ch < fmt.channels; ch++) {
            const base = (i * fmt.channels + ch) * (fmt.bits / 8);
            let v;
            if (fmt.format === 3 && fmt.bits === 32) {
                v = data.readFloatLE(base);
            } else if (fmt.format === 1 && fmt.bits === 16) {
                v = data.readInt16LE(base) / 32768.0;
            } else if (fmt.format === 1 && fmt.bits === 24) {
                const b0 = data[base], b1 = data[base + 1], b2 = data[base + 2];
                let s = b0 | (b1 << 8) | (b2 << 16);
                if (s & 0x800000) s -= 0x1000000;
                v = s / 8388608.0;
            } else if (fmt.format === 1 && fmt.bits === 32) {
                v = data.readInt32LE(base) / 2147483648.0;
            } else {
                throw new Error(`Unsupported WAV format ${fmt.format}/${fmt.bits}`);
            }
            channels[ch][i] = v;
        }
    }
    return { channels, sampleRate: fmt.sampleRate };
}

async function main() {
    const wavPath = process.argv[2];
    if (!wavPath) {
        console.error("usage: node js_parity.js <file.wav>");
        process.exit(2);
    }
    const { channels, sampleRate } = readWav(wavPath);
    const result = await TruePeakDSP.analyzeBuffer(channels, sampleRate, null);
    process.stdout.write(JSON.stringify(result));
}

main().catch((err) => {
    console.error(err.message);
    process.exit(1);
});
