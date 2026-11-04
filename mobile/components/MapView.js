import React, { useRef, useEffect, useMemo } from 'react';
import { StyleSheet, View, Text, Platform } from 'react-native';
import MapView, { Marker, Polyline, Callout } from 'react-native-maps';

/**
 * VibeRide - Interactive Navigation Map Component
 *
 * Implements:
 * 1. GeoJSON [lon, lat] -> Native Maps { latitude, longitude } coordinate mapping.
 * 2. Glow Aesthetic: Overlapping polylines (10px @ 0.35 opacity + 4px @ 1.0 opacity).
 * 3. Dynamic markers for origin, destination, vibe stops (coffee, park, view), and hazards.
 * 4. Automatic bounding box refit on route change.
 */

const isValidCoord = (p) =>
  p &&
  Number.isFinite(p.latitude) &&
  Number.isFinite(p.longitude) &&
  Math.abs(p.latitude) <= 90 &&
  Math.abs(p.longitude) <= 180;

const hasLatLon = (p) => p && Number.isFinite(Number(p.lat)) && Number.isFinite(Number(p.lon));

export default function VibeMapView({
  plan,
  geojson,
  hazards = [],
  userLocation = null,
  style,
}) {
  const mapRef = useRef(null);

  // 1. Transform GeoJSON [lon, lat] coordinates into { latitude, longitude }
  const routeCoordinates = useMemo(() => {
    if (!geojson) return [];

    let coords = [];

    // Cazul A: FeatureCollection (GeoJSON standard)
    if (geojson.features && geojson.features.length > 0) {
      coords = geojson.features[0]?.geometry?.coordinates || [];
    }
    // Cazul B: Rute OSRM / OpenStreetMap
    else if (geojson.routes && geojson.routes.length > 0) {
      coords = geojson.routes[0]?.geometry?.coordinates || [];
    }
    // Cazul C: Feature singular
    else if (geojson.type === 'Feature') {
      coords = geojson.geometry?.coordinates || [];
    }
    // Cazul D: Obiect direct Geometry (LineString)
    else if (geojson.coordinates && Array.isArray(geojson.coordinates)) {
      coords = geojson.coordinates;
    }
    // Cazul E: Array direct de perechi [lon, lat]
    else if (Array.isArray(geojson)) {
      coords = geojson;
    }

    if (!Array.isArray(coords)) return [];

    return coords
      .map((c) =>
        Array.isArray(c)
          ? { latitude: Number(c[1]), longitude: Number(c[0]) }
          : { latitude: Number(c?.latitude), longitude: Number(c?.longitude) }
      )
      .filter(isValidCoord);
  }, [geojson]);

  // 2. Automatically fit map bounds whenever a new route is loaded
  useEffect(() => {
    if (mapRef.current && routeCoordinates.length > 1) {
      mapRef.current.fitToCoordinates(routeCoordinates, {
        edgePadding: { top: 80, right: 50, bottom: 80, left: 50 },
        animated: true,
      });
    }
  }, [routeCoordinates]);

  // Fallback initial center (Bucharest Center - University Square)
  const initialRegion = {
    latitude: 44.4355,
    longitude: 26.1025,
    latitudeDelta: 0.08,
    longitudeDelta: 0.08,
  };

  const getStopEmoji = (type) => {
    switch (type) {
      case 'coffee':
        return '☕';
      case 'park':
        return '🌿';
      case 'viewpoint':
      case 'view':
        return '🏛️';
      case 'fountain':
        return '⛲';
      case 'gelato':
        return '🍦';
      default:
        return '✨';
    }
  };

  const stops = (plan?.intermediate_stops || []).filter(hasLatLon);
  const validHazards = (Array.isArray(hazards) ? hazards : []).filter(hasLatLon);

  return (
    <View style={[styles.container, style]}>
      <MapView
        ref={mapRef}
        style={styles.map}
        initialRegion={initialRegion}
        userInterfaceStyle="dark"
        showsUserLocation={Boolean(userLocation)}
        showsMyLocationButton={false}
        showsCompass={true}
      >
        {/* ================================================================= */}
        {/* GLOW AESTHETIC ROUTE POLYLINES                                    */}
        {/* ================================================================= */}
        {routeCoordinates.length > 1 && (
          <>
            {/* Glow Layer: 10px #fc5200 at 0.35 opacity */}
            <Polyline
              coordinates={routeCoordinates}
              strokeColor="rgba(252, 82, 0, 0.35)"
              strokeWidth={10}
              lineCap="round"
              lineJoin="round"
              zIndex={1}
            />

            {/* Core Razor Line: 4px #fc5200 at 1.0 opacity */}
            <Polyline
              coordinates={routeCoordinates}
              strokeColor="#fc5200"
              strokeWidth={4}
              lineCap="round"
              lineJoin="round"
              zIndex={2}
            />
          </>
        )}

        {/* ================================================================= */}
        {/* ROUTE MARKERS: Origin & Destination                               */}
        {/* ================================================================= */}
        {hasLatLon(plan?.origin) && (
          <Marker
            coordinate={{
              latitude: Number(plan.origin.lat),
              longitude: Number(plan.origin.lon),
            }}
            title={plan.origin.name}
            description="Start of calm ride"
            zIndex={3}
          >
            <View style={[styles.markerBadge, styles.originMarker]}>
              <Text style={styles.markerText}>🚲</Text>
            </View>
          </Marker>
        )}

        {hasLatLon(plan?.destination) && (
          <Marker
            coordinate={{
              latitude: Number(plan.destination.lat),
              longitude: Number(plan.destination.lon),
            }}
            title={plan.destination.name}
            description="Destination"
            zIndex={3}
          >
            <View style={[styles.markerBadge, styles.destinationMarker]}>
              <Text style={styles.markerText}>🏁</Text>
            </View>
          </Marker>
        )}

        {/* ================================================================= */}
        {/* INTERMEDIATE VIBE STOPS (Coffee, Parks, Fountains, Viewpoints)    */}
        {/* ================================================================= */}
        {stops.map((stop, index) => (
          <Marker
            key={`stop-${index}-${stop.lat}-${stop.lon}`}
            coordinate={{
              latitude: Number(stop.lat),
              longitude: Number(stop.lon),
            }}
            title={stop.name}
            description={`Vibe Stop: ${stop.type || 'Scenic point'}`}
            zIndex={4}
          >
            <View style={[styles.markerBadge, styles.vibeMarker]}>
              <Text style={styles.markerText}>{getStopEmoji(stop.type)}</Text>
            </View>
            <Callout>
              <View style={styles.calloutContainer}>
                <Text style={styles.calloutTitle}>{stop.name}</Text>
                <Text style={styles.calloutSubtitle}>
                  Vibe Stop ({stop.type || 'Exploration'})
                </Text>
              </View>
            </Callout>
          </Marker>
        ))}

        {/* ================================================================= */}
        {/* HAZARD WARNING MARKERS (From Spatial Safety Sensor)               */}
        {/* ================================================================= */}
        {validHazards.map((hazard, index) => (
          <Marker
            key={`hazard-${hazard.id ?? index}`}
            coordinate={{
              latitude: Number(hazard.lat),
              longitude: Number(hazard.lon),
            }}
            zIndex={5}
          >
            <View style={[styles.markerBadge, styles.hazardMarker]}>
              <Text style={styles.markerText}>⚠️</Text>
            </View>
            <Callout>
              <View style={styles.calloutContainer}>
                <Text style={styles.calloutAlertTitle}>Hazard Detected</Text>
                <Text style={styles.calloutSubtitle}>
                  {hazard.hazard_type?.replace(/_/g, ' ') || 'Road caution'}
                </Text>
                {hazard.audio_alert && (
                  <Text style={styles.calloutAlertText}>
                    "{hazard.audio_alert}"
                  </Text>
                )}
              </View>
            </Callout>
          </Marker>
        ))}
      </MapView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
  },
  map: {
    width: '100%',
    height: '100%',
  },
  markerBadge: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#ffffff',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 3 },
        shadowOpacity: 0.3,
        shadowRadius: 4,
      },
      android: {
        elevation: 5,
      },
    }),
  },
  originMarker: {
    backgroundColor: '#10b981', // Emerald green
  },
  destinationMarker: {
    backgroundColor: '#3b82f6', // Bright blue
  },
  vibeMarker: {
    backgroundColor: '#8b5cf6', // Violet
  },
  hazardMarker: {
    backgroundColor: '#ef4444', // Red
    borderColor: '#fef08a', // Yellow highlight
  },
  markerText: {
    fontSize: 16,
  },
  calloutContainer: {
    padding: 8,
    minWidth: 140,
    maxWidth: 220,
  },
  calloutTitle: {
    fontWeight: 'bold',
    fontSize: 14,
    color: '#111827',
  },
  calloutSubtitle: {
    fontSize: 12,
    color: '#4b5563',
    marginTop: 2,
    textTransform: 'capitalize',
  },
  calloutAlertTitle: {
    fontWeight: 'bold',
    fontSize: 13,
    color: '#b91c1c',
  },
  calloutAlertText: {
    fontSize: 11,
    fontStyle: 'italic',
    color: '#374151',
    marginTop: 4,
  },
});