/*
 * TruePeak client-side DSP engine.
 * Faithful port of truepeak/analysis (BS.1770-4) to JavaScript so masters
 * can be analyzed locally in the browser without uploading audio.
 * Runs in the browser (global `TruePeakDSP`) and in Node (module.exports)
 * for parity testing against the Python implementation.
 */
"use strict";

const TruePeakDSP = (() => {

const LUFS_OFFSET = -0.691;
const ABS_GATE_LUFS = -70.0;
const REL_GATE_LU = 10.0;
const LRA_REL_GATE_LU = 20.0;
const CLIP_THRESHOLD = 0.999;
const HOP_SECONDS = 0.1;
const BLOCK_HOPS = 64;
const MAX_TIMELINE_POINTS = 2400;
const MAX_WAVEFORM_POINTS = 2048;

const THIRD_OCTAVE_CENTERS = [
    25.0, 31.5, 40.0, 50.0, 63.0, 80.0, 100.0, 125.0, 160.0, 200.0,
    250.0, 315.0, 400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0, 2000.0,
    2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 8000.0, 10000.0, 12500.0,
    16000.0, 20000.0,
];

// 81-tap Kaiser FIR (beta=5.0) used by scipy.signal.resample_poly(x, 4, 1).
const TP_FIR = Float64Array.from([
    -1.4319646207876957e-18, -0.0011305975791844618, -0.002103167861717876,
    -0.0019016679348927714, 3.709041094023895e-18, 0.0029265141089618875,
    0.005018530923471821, 0.004252319066855106, -6.9891223043616e-18,
    -0.0059320518437837155, -0.009790833971198891, -0.008026125461265493,
    1.1214237028997423e-17, 0.010605090076805454, 0.017115155028976113,
    0.013753959070631755, -1.6183952382363036e-17, -0.017579165251157443,
    -0.027983277010958114, -0.02221988556769976, 2.156483064750302e-17,
    0.027866916359520877, 0.044051484099836266, 0.03479525475036112,
    -2.692255913458819e-17, -0.04342308644211484, -0.06868853498568138,
    -0.05442549106878251, 3.177298294598318e-17, 0.06897233879817498,
    0.11058973007292545, 0.08928334853204616, -3.564465655764782e-17,
    -0.1201343501545469, -0.20188442282305533, -0.1739777429715405,
    3.814313342422119e-17, 0.2965428196043752, 0.6334760868798733,
    0.8996325710102085, 1.0006365650891118, 0.8996325710102085,
    0.6334760868798733, 0.2965428196043752, 3.814313342422119e-17,
    -0.1739777429715405, -0.20188442282305533, -0.1201343501545469,
    -3.564465655764782e-17, 0.08928334853204616, 0.11058973007292545,
    0.06897233879817498, 3.177298294598318e-17, -0.05442549106878251,
    -0.06868853498568138, -0.04342308644211484, -2.692255913458819e-17,
    0.03479525475036112, 0.044051484099836266, 0.027866916359520877,
    2.156483064750302e-17, -0.02221988556769976, -0.027983277010958114,
    -0.017579165251157443, -1.6183952382363036e-17, 0.013753959070631755,
    0.017115155028976113, 0.010605090076805454, 1.1214237028997423e-17,
    -0.008026125461265493, -0.009790833971198891, -0.0059320518437837155,
    -6.9891223043616e-18, 0.004252319066855106, 0.005018530923471821,
    0.0029265141089618875, 3.709041094023895e-18, -0.0019016679348927714,
    -0.002103167861717876, -0.0011305975791844618, -1.4319646207876957e-18,
]);

const CHANNEL_WEIGHTS = {
    1: [1.0],
    2: [1.0, 1.0],
    3: [1.0, 1.0, 1.0],
    4: [1.0, 1.0, 1.0, 0.0],
    5: [1.0, 1.0, 1.0, 1.41, 1.41],
    6: [1.0, 1.0, 1.0, 0.0, 1.41, 1.41],
    7: [1.0, 1.0, 1.0, 1.41, 1.41, 1.0, 1.0],
    8: [1.0, 1.0, 1.0, 0.0, 1.41, 1.41, 1.0, 1.0],
};

function channelWeights(nChannels) {
    return CHANNEL_WEIGHTS[nChannels] || new Array(nChannels).fill(1.0);
}

function lufsFromMeanSquare(z) {
    return LUFS_OFFSET + 10.0 * Math.log10(z);
}

function db(value) {
    if (value === null || value === undefined || value <= 0.0) return null;
    return 20.0 * Math.log10(value);
}

function clean(value) {
    if (value === null || value === undefined) return null;
    if (typeof value !== "number") return value;
    return Number.isFinite(value) ? value : null;
}

function roundTo(value, decimals) {
    if (value === null || value === undefined || !Number.isFinite(value)) return null;
    const f = 10 ** decimals;
    return Math.round(value * f) / f;
}

/* ---------------- K-weighting (BS.1770-4) ---------------- */

function kWeightCoefficients(fs) {
    let f0 = 1681.974450955533;
    const gainDb = 3.999843853973347;
    let q = 0.7071752369554196;
    let k = Math.tan(Math.PI * f0 / fs);
    const vh = 10.0 ** (gainDb / 20.0);
    const vb = vh ** 0.4996667741545416;
    const a0 = 1.0 + k / q + k * k;
    const shelfB = [
        (vh + vb * k / q + k * k) / a0,
        2.0 * (k * k - vh) / a0,
        (vh - vb * k / q + k * k) / a0,
    ];
    const shelfA = [
        1.0,
        2.0 * (k * k - 1.0) / a0,
        (1.0 - k / q + k * k) / a0,
    ];
    f0 = 38.13547087602444;
    q = 0.5003270373238773;
    k = Math.tan(Math.PI * f0 / fs);
    const denom = 1.0 + k / q + k * k;
    const hpB = [1.0, -2.0, 1.0];
    const hpA = [
        1.0,
        2.0 * (k * k - 1.0) / denom,
        (1.0 - k / q + k * k) / denom,
    ];
    return { shelfB, shelfA, hpB, hpA };
}

// Direct Form II transposed biquad state (matches scipy lfilter with zi=0).
class Biquad {
    constructor(b, a) {
        this.b0 = b[0]; this.b1 = b[1]; this.b2 = b[2];
        this.a1 = a[1]; this.a2 = a[2];
        this.z1 = 0.0; this.z2 = 0.0;
    }
    step(x) {
        const y = this.b0 * x + this.z1;
        const z1 = this.b1 * x - this.a1 * y + this.z2;
        this.z2 = this.b2 * x - this.a2 * y;
        this.z1 = z1;
        return y;
    }
}

/* ---------------- loudness (integrated / momentary / short-term / LRA) ---------------- */

function slidingMean(z, width) {
    if (z.length < width) return new Float64Array(0);
    const out = new Float64Array(z.length - width + 1);
    let acc = 0.0;
    for (let i = 0; i < width; i++) acc += z[i];
    out[0] = acc / width;
    for (let i = width; i < z.length; i++) {
        acc += z[i] - z[i - width];
        out[i - width + 1] = acc / width;
    }
    return out;
}

function integratedLoudness(blockMeanSquares) {
    const z = [];
    for (const v of blockMeanSquares) {
        if (Number.isFinite(v) && v > 0.0) z.push(v);
    }
    if (!z.length) return null;
    const absThresh = 10.0 ** ((ABS_GATE_LUFS - LUFS_OFFSET) / 10.0);
    const za = z.filter((v) => v > absThresh);
    if (!za.length) return null;
    const mean = za.reduce((a, b) => a + b, 0.0) / za.length;
    const relThreshold = lufsFromMeanSquare(mean) - REL_GATE_LU;
    let keep = za.filter((v) => lufsFromMeanSquare(v) > relThreshold);
    if (!keep.length) keep = za;
    const keepMean = keep.reduce((a, b) => a + b, 0.0) / keep.length;
    return lufsFromMeanSquare(keepMean);
}

function percentile(sorted, q) {
    if (!sorted.length) return NaN;
    const idx = (sorted.length - 1) * (q / 100.0);
    const lo = Math.floor(idx);
    const hi = Math.ceil(idx);
    if (lo === hi) return sorted[lo];
    const frac = idx - lo;
    return sorted[lo] * (1.0 - frac) + sorted[hi] * frac;
}

function loudnessRange(shortTermLufs) {
    const levels = [];
    for (const v of shortTermLufs) {
        if (Number.isFinite(v)) levels.push(v);
    }
    if (levels.length < 2) return null;
    const gated = levels.filter((v) => v > ABS_GATE_LUFS);
    if (gated.length < 2) return null;
    let powerSum = 0.0;
    for (const v of gated) powerSum += 10.0 ** ((v - LUFS_OFFSET) / 10.0);
    const relThreshold = lufsFromMeanSquare(powerSum / gated.length) - LRA_REL_GATE_LU;
    const keep = gated.filter((v) => v > relThreshold);
    if (keep.length < 2) return null;
    keep.sort((a, b) => a - b);
    return percentile(keep, 95) - percentile(keep, 10);
}

// Pass 1: K-weighted filtering + per-hop energies + level + correlation + waveform.
function loudnessAndLevels(channelData, sr, onProgress) {
    const nCh = channelData.length;
    const nFrames = channelData[0].length;
    const weights = channelWeights(nCh);
    const hopFrames = Math.max(1, Math.round(sr * HOP_SECONDS));
    const coeffs = kWeightCoefficients(sr);

    const shelf = [];
    const hp = [];
    for (let ch = 0; ch < nCh; ch++) {
        shelf.push(new Biquad(coeffs.shelfB, coeffs.shelfA));
        hp.push(new Biquad(coeffs.hpB, coeffs.hpA));
    }

    const energies = [];
    const total = new Float64Array(nCh);
    const sumSq = new Float64Array(nCh);
    const peak = new Float64Array(nCh);
    let clipTotal = 0;
    let clipRuns = 0;
    let clipMaxRun = 0;
    const clipCarry = new Float64Array(nCh);
    const corrValues = [];
    let sLr = 0.0, sLl = 0.0, sRr = 0.0;
    const waveMins = [];
    const waveMaxs = [];

    const recordRun = (len) => {
        if (len >= 2) {
            clipRuns += 1;
            if (len > clipMaxRun) clipMaxRun = len;
        }
    };

    const chunkHops = 32;
    const chunkFrames = hopFrames * chunkHops;
    let hopEnergy = 0.0;
    let hopIndex = 0; // frame index within current hop

    for (let start = 0; start < nFrames; start += chunkFrames) {
        const end = Math.min(start + chunkFrames, nFrames);
        for (let i = start; i < end; i++) {
            let mono = 0.0;
            for (let ch = 0; ch < nCh; ch++) {
                const x = channelData[ch][i];
                const z = hp[ch].step(shelf[ch].step(x));
                hopEnergy += weights[ch] * z * z;
                total[ch] += x;
                sumSq[ch] += x * x;
                const ax = Math.abs(x);
                if (ax > peak[ch]) peak[ch] = ax;
                if (ax >= CLIP_THRESHOLD) {
                    clipTotal += 1;
                    clipCarry[ch] += 1;
                } else if (clipCarry[ch]) {
                    recordRun(clipCarry[ch]);
                    clipCarry[ch] = 0;
                }
                mono += x;
            }
            hopIndex += 1;
            if (hopIndex === hopFrames) {
                energies.push(hopEnergy);
                hopEnergy = 0.0;
                hopIndex = 0;
            }
        }
        // per-hop correlation and waveform over the chunk hops
        const hopStart = start;
        const nHops = Math.floor((end - start) / hopFrames);
        for (let hIdx = 0; hIdx <= nHops; hIdx++) {
            const hStart = hopStart + hIdx * hopFrames;
            const hEnd = Math.min(hStart + hopFrames, end);
            if (hEnd <= hStart) break;
            if (nCh === 2) {
                let lr = 0.0, ll = 0.0, rr = 0.0;
                const L = channelData[0];
                const R = channelData[1];
                for (let i = hStart; i < hEnd; i++) {
                    const l = L[i];
                    const r = R[i];
                    lr += l * r; ll += l * l; rr += r * r;
                }
                sLr += lr; sLl += ll; sRr += rr;
                const denom = Math.sqrt(ll * rr);
                corrValues.push(denom > 0.0 ? lr / denom : NaN);
            }
            let mn = Infinity, mx = -Infinity;
            for (let i = hStart; i < hEnd; i++) {
                let m = 0.0;
                for (let ch = 0; ch < nCh; ch++) m += channelData[ch][i];
                m /= nCh;
                if (m < mn) mn = m;
                if (m > mx) mx = m;
            }
            waveMins.push(mn);
            waveMaxs.push(mx);
        }
        if (onProgress) onProgress((end / nFrames));
    }
    for (let ch = 0; ch < nCh; ch++) {
        if (clipCarry[ch]) recordRun(clipCarry[ch]);
    }

    return {
        energies: Float64Array.from(energies),
        hopFrames,
        weights,
        nCh,
        nFrames,
        total, sumSq, peak,
        clipTotal, clipRuns, clipMaxRun,
        corrValues, sLr, sLl, sRr,
        waveMins, waveMaxs,
    };
}

function finishLoudness(energies, hopFrames, sr) {
    const hopSeconds = hopFrames / sr;
    const nullResult = {
        integrated_lufs: null,
        momentary_max_lufs: null,
        short_term_max_lufs: null,
        lra_lu: null,
        t_momentary: [],
        momentary: [],
        t_short_term: [],
        short_term: [],
    };
    if (!energies.length) return nullResult;
    let maxE = 0.0;
    for (const e of energies) if (e > maxE) maxE = e;
    if (maxE <= 0.0) return nullResult;

    const z = new Float64Array(energies.length);
    for (let i = 0; i < energies.length; i++) z[i] = energies[i] / hopFrames;
    const zMomentary = slidingMean(z, 4);
    const zShortTerm = slidingMean(z, 30);
    const momentary = new Array(zMomentary.length);
    for (let i = 0; i < zMomentary.length; i++) {
        momentary[i] = lufsFromMeanSquare(zMomentary[i]);
    }
    const shortTerm = new Array(zShortTerm.length);
    for (let i = 0; i < zShortTerm.length; i++) {
        shortTerm[i] = lufsFromMeanSquare(zShortTerm[i]);
    }
    const tMomentary = new Array(zMomentary.length);
    for (let i = 0; i < zMomentary.length; i++) tMomentary[i] = (i + 2.0) * hopSeconds;
    const tShortTerm = new Array(zShortTerm.length);
    for (let i = 0; i < zShortTerm.length; i++) tShortTerm[i] = (i + 15.0) * hopSeconds;

    const integrated = integratedLoudness(zMomentary);
    const lra = loudnessRange(shortTerm);
    let mMax = null;
    for (const v of momentary) {
        if (Number.isFinite(v) && (mMax === null || v > mMax)) mMax = v;
    }
    let sMax = null;
    for (const v of shortTerm) {
        if (Number.isFinite(v) && (sMax === null || v > sMax)) sMax = v;
    }
    return {
        integrated_lufs: integrated,
        momentary_max_lufs: mMax,
        short_term_max_lufs: sMax,
        lra_lu: lra,
        t_momentary: tMomentary,
        momentary,
        t_short_term: tShortTerm,
        short_term: shortTerm,
    };
}

/* ---------------- Welch spectrum (1/3 octave) ---------------- */

function hannPeriodic(n) {
    const w = new Float64Array(n);
    for (let i = 0; i < n; i++) {
        w[i] = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * i) / n);
    }
    return w;
}

// Iterative radix-2 FFT (in place, arrays of real/imag parts).
function fft(re, im) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
        let bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            const tr = re[i]; re[i] = re[j]; re[j] = tr;
            const ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }
    for (let len = 2; len <= n; len <<= 1) {
        const ang = (-2.0 * Math.PI) / len;
        const wr = Math.cos(ang);
        const wi = Math.sin(ang);
        const half = len >> 1;
        for (let i = 0; i < n; i += len) {
            let cwr = 1.0, cwi = 0.0;
            for (let j = 0; j < half; j++) {
                const ur = re[i + j];
                const ui = im[i + j];
                const vr = re[i + j + half] * cwr - im[i + j + half] * cwi;
                const vi = re[i + j + half] * cwi + im[i + j + half] * cwr;
                re[i + j] = ur + vr;
                im[i + j] = ui + vi;
                re[i + j + half] = ur - vr;
                im[i + j + half] = ui - vi;
                const nwr = cwr * wr - cwi * wi;
                cwi = cwr * wi + cwi * wr;
                cwr = nwr;
            }
        }
    }
}

// Welch PSD matching scipy.signal.welch(x, fs, nperseg=8192): periodic Hann,
// 50% overlap, constant detrend, density scaling, one-sided.
function welchPsd(x, fs, nperseg, window, winPow) {
    const noverlap = nperseg >> 1;
    const step = nperseg - noverlap;
    const nBins = nperseg / 2 + 1;
    const acc = new Float64Array(nBins);
    let count = 0;
    const re = new Float64Array(nperseg);
    const im = new Float64Array(nperseg);
    for (let start = 0; start + nperseg <= x.length; start += step) {
        let mean = 0.0;
        for (let i = 0; i < nperseg; i++) mean += x[start + i];
        mean /= nperseg;
        for (let i = 0; i < nperseg; i++) {
            re[i] = (x[start + i] - mean) * window[i];
            im[i] = 0.0;
        }
        fft(re, im);
        for (let k = 0; k < nBins; k++) {
            let p = (re[k] * re[k] + im[k] * im[k]) / (fs * winPow);
            if (k > 0 && k < nBins - 1) p *= 2.0;
            acc[k] += p;
        }
        count += 1;
    }
    if (!count) return null;
    for (let k = 0; k < nBins; k++) acc[k] /= count;
    return acc;
}

function spectrumThirdOctave(channelData, sr, onProgress) {
    const nCh = channelData.length;
    const nFrames = channelData[0].length;
    const hopFrames = Math.max(1, Math.round(sr * HOP_SECONDS));
    const blockFrames = hopFrames * BLOCK_HOPS;
    const nperseg = 8192;
    const every = 4;
    const nBins = nperseg / 2 + 1;
    const window = hannPeriodic(nperseg);
    let winPow = 0.0;
    for (let i = 0; i < nperseg; i++) winPow += window[i] * window[i];

    let acc = null;
    let count = 0;
    let blockIndex = 0;
    const mono = new Float64Array(Math.min(blockFrames, nFrames));
    for (let start = 0; start < nFrames; start += blockFrames, blockIndex++) {
        if (blockIndex % every) continue;
        const end = Math.min(start + blockFrames, nFrames);
        const n = end - start;
        if (Math.min(nperseg, n) < 256) continue;
        for (let i = 0; i < n; i++) {
            let m = 0.0;
            for (let ch = 0; ch < nCh; ch++) m += channelData[ch][start + i];
            mono[i] = m / nCh;
        }
        const blockPsd = welchPsd(mono.subarray(0, n), sr, nperseg, window, winPow);
        if (!blockPsd) continue;
        if (acc === null) acc = new Float64Array(nBins);
        for (let k = 0; k < nBins; k++) acc[k] += blockPsd[k];
        count += 1;
        if (onProgress) onProgress(end / nFrames);
    }
    if (!count || acc === null) return null;
    for (let k = 0; k < nBins; k++) acc[k] /= count;

    const freqs = new Float64Array(nBins);
    for (let k = 0; k < nBins; k++) freqs[k] = (k * sr) / nperseg;
    const bands = [];
    for (const center of THIRD_OCTAVE_CENTERS) {
        const lo = center / 2.0 ** (1.0 / 6.0);
        const hi = center * 2.0 ** (1.0 / 6.0);
        let energy = 0.0;
        let any = false;
        for (let k = 0; k < nBins; k++) {
            if (freqs[k] >= lo && freqs[k] < hi) {
                energy += acc[k];
                any = true;
            }
        }
        bands.push(any ? 10.0 * Math.log10(energy + 1e-20) : null);
    }
    return {
        freqs: THIRD_OCTAVE_CENTERS.map((f) => roundTo(f, 1)),
        db: bands.map((v) => roundTo(v, 2)),
    };
}

/* ---------------- true peak (4x oversampling, BS.1770 polyphase FIR) ---------------- */

function truePeakChannel(x, onProgress) {
    const n = x.length;
    const phases = [];
    for (let p = 0; p < 4; p++) {
        const taps = [];
        for (let m = p; m < TP_FIR.length; m += 4) taps.push(TP_FIR[m]);
        phases.push(Float64Array.from(taps));
    }
    let maxLinear = 0.0;
    const progressStep = Math.max(1, Math.floor(n / 64));
    for (let p = 0; p < 4; p++) {
        const hp = phases[p];
        const L = hp.length;
        for (let o = 0; o < n; o++) {
            const m0 = o - n + 1 > 0 ? o - n + 1 : 0;
            const m1 = o < L - 1 ? o : L - 1;
            let acc = 0.0;
            for (let m = m0; m <= m1; m++) acc += hp[m] * x[o - m];
            const a = acc < 0 ? -acc : acc;
            if (a > maxLinear) maxLinear = a;
            if (onProgress && (o % progressStep) === 0) {
                onProgress((p + o / n) / 4);
            }
        }
    }
    return maxLinear;
}

/* ---------------- downsampling / compaction (matches compact_result) ---------------- */

function downsample(series, maxPoints = MAX_TIMELINE_POINTS, keepMax = true) {
    const arr = series;
    if (!arr.length) return [];
    let out = arr;
    if (arr.length > maxPoints) {
        const factor = Math.ceil(arr.length / maxPoints);
        out = [];
        for (let i = 0; i < arr.length; i += factor) {
            const slice = arr.slice(i, i + factor);
            if (keepMax) {
                let m = -Infinity;
                for (const v of slice) if (v > m) m = v;
                out.push(m);
            } else {
                let s = 0.0;
                for (const v of slice) s += v;
                out.push(s / slice.length);
            }
        }
    }
    return Array.from(out, (v) => (Number.isFinite(v) ? roundTo(v, 2) : null));
}

function downsampleWaveform(mins, maxs) {
    if (!mins.length) return { min: [], max: [] };
    let outMin = mins;
    let outMax = maxs;
    if (mins.length > MAX_WAVEFORM_POINTS) {
        const factor = Math.ceil(mins.length / MAX_WAVEFORM_POINTS);
        outMin = [];
        outMax = [];
        for (let i = 0; i < mins.length; i += factor) {
            outMin.push(Math.min(...mins.slice(i, i + factor)));
            outMax.push(Math.max(...maxs.slice(i, i + factor)));
        }
    }
    return {
        min: outMin.map((v) => roundTo(v, 4)),
        max: outMax.map((v) => roundTo(v, 4)),
    };
}

/* ---------------- main entry ---------------- */

// channelData: array of Float32Array (one per channel). Returns the same
// compact JSON shape the server produces for /analyze results.
async function analyzeBuffer(channelData, sr, onProgress) {
    const progress = (frac, phase) => {
        if (onProgress) onProgress(frac, phase);
    };
    const tick = () => new Promise((r) => setTimeout(r, 0));

    const nCh = channelData.length;
    const nFrames = channelData[0].length;

    progress(0.0, "loudness");
    const pass1 = loudnessAndLevels(channelData, sr, null);
    await tick();
    const loudness = finishLoudness(pass1.energies, pass1.hopFrames, sr);
    progress(0.55, "spectrum");

    const spectrum = spectrumThirdOctave(channelData, sr, null);
    await tick();
    progress(0.7, "true peak");

    const tpPerChannel = [];
    for (let ch = 0; ch < nCh; ch++) {
        tpPerChannel.push(db(truePeakChannel(channelData[ch], null)));
        progress(0.7 + 0.3 * ((ch + 1) / nCh), "true peak");
        await tick();
    }
    const tpLinearMax = Math.max(
        ...tpPerChannel.map((v) => (v === null ? -Infinity : 10 ** (v / 20)))
    );
    const truePeak = tpPerChannel.every((v) => v === null)
        ? null
        : db(tpLinearMax);

    // level summary
    const frames = pass1.nFrames;
    const rmsPerChannel = [];
    for (let ch = 0; ch < nCh; ch++) {
        rmsPerChannel.push(db(Math.sqrt(pass1.sumSq[ch] / frames)));
    }
    let sumAll = 0.0;
    for (let ch = 0; ch < nCh; ch++) sumAll += pass1.sumSq[ch];
    const rmsOverall = db(Math.sqrt(sumAll / (frames * nCh)));
    const dcPerChannel = [];
    for (let ch = 0; ch < nCh; ch++) dcPerChannel.push(pass1.total[ch] / frames);
    let samplePeak = 0.0;
    for (let ch = 0; ch < nCh; ch++) {
        if (pass1.peak[ch] > samplePeak) samplePeak = pass1.peak[ch];
    }
    const samplePeakDb = db(samplePeak);
    const clipping = pass1.clipTotal > 0
        ? {
            total_samples: pass1.clipTotal,
            runs: pass1.clipRuns,
            max_run_samples: pass1.clipMaxRun,
        }
        : null;

    const analysis = {
        frames,
        sample_peak_dbfs: samplePeakDb,
        sample_peak_dbfs_per_channel: Array.from(pass1.peak, (p) => db(p)),
        rms_db: rmsOverall,
        rms_db_per_channel: rmsPerChannel,
        dc_offset_per_channel: dcPerChannel,
        clipping,
        true_peak_dbtp: truePeak,
        true_peak_dbtp_per_channel: tpPerChannel,
        loudness_integrated_lufs: loudness.integrated_lufs,
        momentary_max_lufs: loudness.momentary_max_lufs,
        short_term_max_lufs: loudness.short_term_max_lufs,
        lra_lu: loudness.lra_lu,
        plr_db: (truePeak !== null && loudness.integrated_lufs !== null)
            ? truePeak - loudness.integrated_lufs
            : null,
        crest_factor_db: (samplePeakDb !== null && rmsOverall !== null)
            ? samplePeakDb - rmsOverall
            : null,
    };

    if (nCh === 2) {
        const finite = pass1.corrValues.filter((v) => Number.isFinite(v));
        const denom = Math.sqrt(pass1.sLl * pass1.sRr);
        analysis.phase_correlation = denom > 0.0 ? pass1.sLr / denom : null;
        let corrMin = null;
        if (finite.length >= 10) {
            for (let i = 0; i + 10 <= finite.length; i++) {
                let s = 0.0;
                for (let j = 0; j < 10; j++) s += finite[i + j];
                const m = s / 10.0;
                if (corrMin === null || m < corrMin) corrMin = m;
            }
        } else if (finite.length) {
            corrMin = Math.min(...finite);
        }
        analysis.phase_correlation_min = corrMin;
        analysis.lr_balance_db = (rmsPerChannel[0] !== null && rmsPerChannel[1] !== null)
            ? rmsPerChannel[0] - rmsPerChannel[1]
            : null;
    } else {
        analysis.phase_correlation = null;
        analysis.phase_correlation_min = null;
        analysis.lr_balance_db = null;
    }

    for (const key of Object.keys(analysis)) {
        if (Array.isArray(analysis[key])) {
            analysis[key] = analysis[key].map(clean);
        } else {
            analysis[key] = clean(analysis[key]);
        }
    }
    if (analysis.clipping) {
        analysis.clipping = {
            total_samples: analysis.clipping.total_samples,
            runs: analysis.clipping.runs,
            max_run_samples: analysis.clipping.max_run_samples,
        };
    }

    return {
        sample_rate: sr,
        channels: nCh,
        duration_s: Math.round((nFrames / sr) * 1000) / 1000,
        analysis,
        timeline: {
            t_momentary: downsample(loudness.t_momentary, MAX_TIMELINE_POINTS, false),
            momentary: downsample(loudness.momentary, MAX_TIMELINE_POINTS, true),
            t_short_term: downsample(loudness.t_short_term, MAX_TIMELINE_POINTS, false),
            short_term: downsample(loudness.short_term, MAX_TIMELINE_POINTS, true),
        },
        spectrum,
        waveform: downsampleWaveform(pass1.waveMins, pass1.waveMaxs),
    };
}

/* ---------------- verdicts / album (mirror of server logic) ---------------- */

function buildVerdicts(analysis, platforms) {
    const integrated = analysis.loudness_integrated_lufs;
    const truePeak = analysis.true_peak_dbtp;
    return platforms.map((p) => {
        let playbackGain = null;
        if (integrated !== null && integrated !== undefined) {
            playbackGain = Math.round((p.target_lufs - integrated) * 10) / 10;
        }
        let status = "na";
        if (playbackGain !== null) {
            if (playbackGain > 1.0) status = "quiet";
            else if (playbackGain < -1.0) status = "loud";
            else status = "on_target";
        }
        const truePeakOk = (truePeak !== null && truePeak !== undefined)
            ? truePeak <= p.max_tp_dbtp
            : null;
        return {
            id: p.id,
            label: p.label,
            target_lufs: p.target_lufs,
            max_tp_dbtp: p.max_tp_dbtp,
            playback_gain_db: playbackGain,
            status,
            true_peak_ok: truePeakOk,
        };
    });
}

function albumSummary(results) {
    const valid = results.filter((r) => !r.error);
    const lufs = valid.map((r) => r.analysis.loudness_integrated_lufs).filter((v) => v !== null && v !== undefined);
    const tp = valid.map((r) => r.analysis.true_peak_dbtp).filter((v) => v !== null && v !== undefined);
    const lra = valid.map((r) => r.analysis.lra_lu).filter((v) => v !== null && v !== undefined);
    return {
        track_count: valid.length,
        error_count: results.length - valid.length,
        lufs_min: lufs.length ? Math.min(...lufs) : null,
        lufs_max: lufs.length ? Math.max(...lufs) : null,
        lufs_spread_lu: lufs.length > 1 ? Math.max(...lufs) - Math.min(...lufs) : null,
        max_true_peak_dbtp: tp.length ? Math.max(...tp) : null,
        mean_lra_lu: lra.length ? lra.reduce((a, b) => a + b, 0) / lra.length : null,
        tracks: valid.map((r) => ({
            filename: r.filename,
            loudness_integrated_lufs: r.analysis.loudness_integrated_lufs,
            true_peak_dbtp: r.analysis.true_peak_dbtp,
            lra_lu: r.analysis.lra_lu,
        })),
    };
}

return {
    analyzeBuffer,
    buildVerdicts,
    albumSummary,
    // exported for tests
    kWeightCoefficients,
    integratedLoudness,
    loudnessRange,
    truePeakChannel,
    welchPsd,
};

})();

if (typeof module !== "undefined" && module.exports) {
    module.exports = TruePeakDSP;
}
if (typeof window !== "undefined") {
    window.TruePeakDSP = TruePeakDSP;
}
