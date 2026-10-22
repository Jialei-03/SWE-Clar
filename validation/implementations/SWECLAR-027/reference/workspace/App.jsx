import React, { useEffect, useRef, useState } from 'react';
import {
  Image,
  PanResponder,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { displayRating, transition } from './model';
import { decodeImage } from './image';

const DEFAULT_RADIUS = 35;

export default function App({ config }) {
  const routes = Array.isArray(config?.routes) ? config.routes : [];
  const [state, setState] = useState(() => ({
    route: routes[0] ?? '',
    openNow: false,
    error: '',
  }));
  const [dragging, setDragging] = useState(false);
  const [slider, setSlider] = useState(DEFAULT_RADIUS);
  const [facilityImage, setFacilityImage] = useState(config?.facilityImage || '');
  const [imageError, setImageError] = useState('');
  const unknownRoute = (() => {
    let candidate = 'missing';
    let suffix = 0;
    while (routes.includes(candidate)) {
      suffix += 1;
      candidate = `__unknown_route_${suffix}`;
    }
    return candidate;
  })();

  const sliderWidth = useRef(1);
  const sliderStart = useRef(DEFAULT_RADIUS);
  const sliderValue = useRef(DEFAULT_RADIUS);
  const draggingRef = useRef(false);
  const imageEpoch = useRef(0);

  const event = (nextEvent) => {
    setState((previous) => transition(previous, nextEvent, config));
  };

  const updateSlider = (nextValue) => {
    const bounded = Math.max(0, Math.min(100, nextValue));
    sliderValue.current = bounded;
    setSlider(bounded);
  };

  const stopDragging = () => {
    draggingRef.current = false;
    setDragging(false);
  };

  const preventGestureDefault = (gestureEvent) => {
    if (typeof gestureEvent?.preventDefault === 'function') {
      gestureEvent.preventDefault();
    } else if (typeof gestureEvent?.nativeEvent?.preventDefault === 'function') {
      gestureEvent.nativeEvent.preventDefault();
    }
  };

  // PanResponder handles both browser mouse drags and touch drags.  Keeping
  // touch-action disabled on the control and disabling the parent ScrollView
  // while the responder owns the gesture prevents a horizontal drag from
  // becoming a vertical scroll.
  const responder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (gestureEvent) => {
        preventGestureDefault(gestureEvent);
        sliderStart.current = sliderValue.current;
        draggingRef.current = true;
        setDragging(true);
      },
      onPanResponderMove: (gestureEvent, gestureState) => {
        preventGestureDefault(gestureEvent);
        const width = Math.max(1, sliderWidth.current);
        updateSlider(sliderStart.current + (gestureState.dx / width) * 100);
      },
      onPanResponderRelease: (gestureEvent) => {
        preventGestureDefault(gestureEvent);
        stopDragging();
      },
      onPanResponderTerminate: stopDragging,
      onPanResponderTerminationRequest: () => false,
      onShouldBlockNativeResponder: () => true,
    }),
  ).current;

  useEffect(() => {
    // These window-level endings cover a pointer/touch released outside the
    // slider and browser cancellation/blur, so scrolling cannot remain locked.
    const endGesture = () => stopDragging();
    window.addEventListener('blur', endGesture);
    window.addEventListener('pointerup', endGesture);
    window.addEventListener('pointercancel', endGesture);
    window.addEventListener('mouseup', endGesture);
    window.addEventListener('touchend', endGesture);
    window.addEventListener('touchcancel', endGesture);

    return () => {
      window.removeEventListener('blur', endGesture);
      window.removeEventListener('pointerup', endGesture);
      window.removeEventListener('pointercancel', endGesture);
      window.removeEventListener('mouseup', endGesture);
      window.removeEventListener('touchend', endGesture);
      window.removeEventListener('touchcancel', endGesture);
      imageEpoch.current += 1;
    };
  }, []);

  async function selectImage(selectEvent) {
    const input = selectEvent?.currentTarget || selectEvent?.target;
    // Increment before checking for a file.  A cancelled newer chooser action
    // must invalidate an older decode that is still in flight.
    const epoch = ++imageEpoch.current;
    const file = input?.files?.[0];
    if (input) input.value = '';
    if (!file) return;

    try {
      const imageData = await decodeImage(file);
      if (epoch !== imageEpoch.current) return;
      setFacilityImage(imageData);
      setImageError('');
    } catch {
      if (epoch === imageEpoch.current) setImageError('unsupported_asset');
    }
  }

  const renderHome = () => (
    <>
      <Pressable
        testID="filter-label"
        accessibilityRole="checkbox"
        aria-checked={state.openNow ? 'true' : 'false'}
        onPress={() => event({ type: 'toggle_filter' })}
        style={styles.filter}
      >
        <View
          testID="filter-box"
          style={[styles.box, state.openNow && styles.checked]}
        >
          <Text>{state.openNow ? '✓' : ''}</Text>
        </View>
        <Text>Open now — include currently available places</Text>
      </Pressable>

      <View style={styles.card}>
        <Text style={styles.heading}>{config?.placeName || ''}</Text>
        <Text testID="rating" style={styles.rating}>
          {displayRating(config?.rating)}
        </Text>
        <Text>Visitor rating</Text>
      </View>

      <Text style={styles.label}>Search radius</Text>
      <View
        testID="slider"
        accessibilityRole="slider"
        accessibilityLabel="Search radius"
        accessibilityValue={{
          min: 0,
          max: 100,
          now: Math.round(slider),
        }}
        {...responder.panHandlers}
        onLayout={(layoutEvent) => {
          sliderWidth.current = Math.max(1, layoutEvent.nativeEvent.layout.width);
        }}
        style={[styles.slider, dragging && styles.sliderDragging]}
      >
        <View style={styles.rail} />
        <View
          testID="slider-thumb"
          style={[styles.thumb, { left: `${slider}%` }]}
        />
      </View>
      <Text testID="slider-value">{Math.round(slider)} km</Text>

      {Array.from({ length: 14 }, (_, index) => (
        <View key={index} style={styles.row}>
          <Text>Sample place {index + 1}</Text>
          <Text>Generated local listing</Text>
        </View>
      ))}
    </>
  );

  const renderProfile = () => (
    <>
      <Text>Facility image</Text>
      <Image
        testID="facility-image"
        source={{ uri: facilityImage }}
        style={styles.photo}
      />
      <label style={styles.fileLabel}>
        Select facility image
        <input
          data-testid="image-picker"
          type="file"
          accept="image/png,image/jpeg"
          onClick={() => {
            // A real chooser can be cancelled without firing change.  Opening
            // it still represents a newer selection attempt, so invalidate a
            // decode from an earlier attempt immediately.
            imageEpoch.current += 1;
          }}
          onChange={selectImage}
          style={styles.fileInput}
        />
      </label>
      <Text testID="image-error" accessibilityRole="alert">
        {imageError}
      </Text>
      <Text>Account avatar</Text>
      <Image
        testID="account-image"
        source={{ uri: config?.accountImage || '' }}
        style={styles.avatar}
      />
    </>
  );

  const renderScreen = () => {
    if (state.route === 'home') return renderHome();
    if (state.route === 'saved') {
      return <Text>No saved places in this fixture.</Text>;
    }
    if (state.route === 'profile') return renderProfile();
    return <Text>Content for the {String(state.route)} route.</Text>;
  };

  return (
    <View style={styles.shell}>
      <Text role="heading" aria-level={1} style={styles.title}>
        Field notebook
      </Text>
      <Text style={styles.subtitle}>Independent navigation and interaction fixture</Text>

      <View style={styles.tabs}>
        {routes.map((route) => (
          <Pressable
            key={route}
            testID={`tab-${route}`}
            accessibilityRole="button"
            onPress={() => event({ type: 'navigate', route })}
            style={[styles.tab, state.route === route && styles.active]}
          >
            <Text>{route}</Text>
          </Pressable>
        ))}
        <Pressable
          testID="unknown-route"
          accessibilityRole="button"
          onPress={() => event({ type: 'navigate', route: unknownRoute })}
          style={styles.tab}
        >
          <Text>Test missing route</Text>
        </Pressable>
      </View>

      <Text testID="route-error" accessibilityRole="alert">
        {state.error}
      </Text>

      <ScrollView
        testID="content-scroll"
        style={styles.scroll}
        scrollEnabled={!dragging}
        contentContainerStyle={styles.content}
      >
        <View testID={`screen-${state.route}`}>
          <Text style={styles.heading} accessibilityRole="header">
            {state.route === 'home'
              ? 'Discover places'
              : state.route === 'saved'
                ? 'Saved places'
                : state.route === 'profile'
                  ? 'Facility profile'
                  : `${String(state.route)} screen`}
          </Text>
          {renderScreen()}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    maxWidth: 760,
    width: '100%',
    alignSelf: 'center',
    padding: 24,
  },
  title: {
    fontSize: 30,
    fontWeight: '700',
    color: '#173e48',
  },
  subtitle: {
    color: '#577179',
    marginTop: 8,
    marginBottom: 24,
  },
  tabs: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  tab: {
    padding: 12,
    backgroundColor: '#e6eeef',
    borderRadius: 7,
  },
  active: {
    backgroundColor: '#a9d8d0',
  },
  scroll: {
    height: 550,
    flexGrow: 0,
    marginTop: 18,
    borderWidth: 1,
    borderColor: '#cadbde',
    borderRadius: 8,
  },
  content: {
    padding: 20,
  },
  heading: {
    fontSize: 22,
    fontWeight: '600',
    marginBottom: 16,
  },
  filter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 14,
    flexWrap: 'wrap',
  },
  box: {
    height: 24,
    width: 24,
    borderWidth: 2,
    borderColor: '#42796f',
    alignItems: 'center',
    justifyContent: 'center',
  },
  checked: {
    backgroundColor: '#a9d8d0',
  },
  card: {
    padding: 20,
    backgroundColor: '#f0f6f5',
    borderRadius: 8,
    marginVertical: 14,
  },
  rating: {
    fontSize: 32,
    color: '#256258',
  },
  label: {
    fontSize: 17,
    marginVertical: 12,
  },
  slider: {
    height: 44,
    marginHorizontal: 12,
    touchAction: 'none',
    userSelect: 'none',
  },
  sliderDragging: {
    // Retain the visual control while its parent scroll view is temporarily
    // disabled; this also makes the active gesture obvious to keyboard/visual
    // inspection without affecting the value calculation.
    opacity: 0.92,
  },
  rail: {
    position: 'absolute',
    top: 19,
    left: 0,
    right: 0,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#d2e4df',
  },
  thumb: {
    position: 'absolute',
    top: 9,
    width: 26,
    height: 26,
    marginLeft: -13,
    borderRadius: 13,
    backgroundColor: '#31786b',
  },
  row: {
    paddingVertical: 22,
    borderBottomWidth: 1,
    borderColor: '#e0e9e9',
    gap: 6,
  },
  photo: {
    width: 220,
    height: 150,
    resizeMode: 'contain',
    backgroundColor: '#edf2f2',
  },
  avatar: {
    width: 80,
    height: 80,
    resizeMode: 'contain',
  },
  fileLabel: {
    display: 'block',
    margin: '16px 0',
  },
  fileInput: {
    display: 'block',
    maxWidth: '100%',
    marginTop: 10,
  },
});
