// Observe the final Web Audio destination without requiring candidate analysers.
module.exports = function installAudioObserver() {
  const connect = AudioNode.prototype.connect;
  const disconnect = AudioNode.prototype.disconnect;
  const destinations = new WeakMap();
  const meters = [];
  function meter(destination) {
    if (!destinations.has(destination)) {
      const context = destination.context;
      const analyser = context.createAnalyser();
      analyser.fftSize = 8192;
      analyser.smoothingTimeConstant = 0;
      connect.call(analyser, destination);
      destinations.set(destination, analyser);
      meters.push(analyser);
    }
    return destinations.get(destination);
  }
  AudioNode.prototype.connect = function (target, ...args) {
    const routed = target instanceof AudioDestinationNode ? meter(target) : target;
    const value = connect.call(this, routed, ...args);
    return target instanceof AudioNode ? target : value;
  };
  AudioNode.prototype.disconnect = function (target, ...args) {
    if (!arguments.length) return disconnect.call(this);
    return disconnect.call(this, destinations.get(target) || target, ...args);
  };
  window.readObservedAudio = () => meters.map(a => {
    const bins = new Float32Array(a.frequencyBinCount);
    a.getFloatFrequencyData(bins);
    let index = 0;
    for (let i = 1; i < bins.length; i++) if (bins[i] > bins[index]) index = i;
    return {state:a.context.state, time:a.context.currentTime, hz: index * a.context.sampleRate / a.fftSize,
      power: Number.isFinite(bins[index]) ? bins[index] : -200};
  });
};
