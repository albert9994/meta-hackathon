import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  Modal,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { auditStreet } from '../utils/api';
import { colors, humanize, radius } from '../utils/theme';

/**
 * Spatial Safety Sensor: photograph the street ahead, get a rider-focused safety read.
 *
 * Props
 *   visible        boolean
 *   onClose()      required
 *   onResult(result)   called once per successful scan with the /api/vision/audit response.
 *                      Hook this to mobile/utils/audio.js so result.audio_alert is spoken
 *                      into the rider's earphones.
 *   coords         optional { latitude, longitude } of the current position. It is only
 *                  uploaded if the rider switches "Share hazard anonymously" on.
 */
export default function VisionAuditModal({ visible, onClose, onResult, coords }) {
  const [phase, setPhase] = useState('idle'); // idle | capturing | analyzing | done | error
  const [photoUri, setPhotoUri] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [shareHazard, setShareHazard] = useState(false);
  const mounted = useRef(true);
  const busy = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!visible) {
      setPhase('idle');
      setPhotoUri(null);
      setResult(null);
      setError(null);
      setPermissionDenied(false);
      busy.current = false;
    }
  }, [visible]);

  const scan = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setError(null);
    setResult(null);
    setPermissionDenied(false);

    try {
      setPhase('capturing');
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) {
        if (mounted.current) {
          setPermissionDenied(true);
          setError('Camera access is needed to scan the street ahead.');
          setPhase('error');
        }
        return;
      }

      const capture = await ImagePicker.launchCameraAsync({ quality: 0.4, base64: true, exif: false });
      if (capture.canceled) {
        if (mounted.current) setPhase('idle');
        return;
      }
      const asset = capture.assets && capture.assets[0];
      if (!asset || !asset.base64) {
        throw new Error('The photo could not be read. Please try again.');
      }
      if (mounted.current) {
        setPhotoUri(asset.uri);
        setPhase('analyzing');
      }

      const payload = { image_base64: asset.base64 };
      if (shareHazard && coords && typeof coords.latitude === 'number' && typeof coords.longitude === 'number') {
        payload.lat = coords.latitude;
        payload.lon = coords.longitude;
      }
      const audit = await auditStreet(payload);
      if (!audit || typeof audit.audio_alert !== 'string') {
        throw new Error('The scanner returned an unexpected answer. Please try again.');
      }
      if (mounted.current) {
        setResult(audit);
        setPhase('done');
      }
      if (onResult) {
        try {
          onResult(audit);
        } catch (_) {
          /* a faulty callback (e.g. text-to-speech) must not hide the scan result */
        }
      }
    } catch (err) {
      if (mounted.current) {
        setError(err.message || 'Scan failed. Please try again.');
        setPhase('error');
      }
    } finally {
      busy.current = false;
    }
  }, [shareHazard, coords, onResult]);

  const hasCoords = !!coords && typeof coords.latitude === 'number' && typeof coords.longitude === 'number';
  const hazardColor = result && result.hazard_detected ? colors.warn : colors.calm;

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.sheet}>
          <View style={styles.headerRow}>
            <Text style={styles.title}>Street Scan</Text>
            <TouchableOpacity onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
              <Text style={styles.close}>✕</Text>
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={styles.body}>
            <Text style={styles.subtitle}>
              Point at the path ahead. VibeRide checks surface, shade and hazards and tells you through your earphones.
            </Text>

            {photoUri ? <Image source={{ uri: photoUri }} style={styles.photo} resizeMode="cover" /> : null}

            {phase === 'analyzing' ? (
              <View style={styles.center}>
                <ActivityIndicator size="large" color={colors.accent} />
                <Text style={styles.muted}>Reading the street…</Text>
              </View>
            ) : null}

            {phase === 'done' && result ? (
              <View style={styles.resultCard}>
                <View style={[styles.alertBox, { borderColor: hazardColor }]}>
                  <Text style={styles.alertText}>{result.audio_alert}</Text>
                </View>
                <Row label="Bike friendly" value={result.bike_friendly ? 'Yes' : 'No'} valueColor={result.bike_friendly ? colors.calm : colors.danger} />
                <Row label="Surface" value={humanize(result.surface) || 'unknown'} />
                <Row label="Shade" value={humanize(result.shade_level) || 'unknown'} />
                <Row label="Hazard" value={result.hazard_detected ? humanize(result.hazard_detected) : 'none spotted'} valueColor={hazardColor} />
              </View>
            ) : null}

            {phase === 'error' && error ? (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>{error}</Text>
                {permissionDenied ? (
                  <TouchableOpacity onPress={() => Linking.openSettings()}>
                    <Text style={styles.link}>Open settings</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            ) : null}

            <View style={styles.shareRow}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                <Text style={styles.shareTitle}>Share hazard anonymously</Text>
                <Text style={styles.muted}>
                  {hasCoords
                    ? 'Adds a rounded, anonymous pin to the community hazard map. No name, no photo.'
                    : 'Location is not available, so nothing will be shared.'}
                </Text>
              </View>
              <Switch
                value={shareHazard && hasCoords}
                onValueChange={setShareHazard}
                disabled={!hasCoords || phase === 'analyzing'}
                trackColor={{ true: colors.calm, false: colors.border }}
              />
            </View>

            <TouchableOpacity
              style={[styles.primary, (phase === 'analyzing' || phase === 'capturing') && styles.disabled]}
              onPress={scan}
              disabled={phase === 'analyzing' || phase === 'capturing'}
              accessibilityRole="button"
            >
              <Text style={styles.primaryText}>{phase === 'done' || phase === 'error' ? 'Scan again' : '📷  Scan the street'}</Text>
            </TouchableOpacity>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function Row({ label, value, valueColor }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, valueColor ? { color: valueColor } : null]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: colors.overlay, justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    maxHeight: '90%',
    borderWidth: 1,
    borderColor: colors.border,
  },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 18, paddingBottom: 4 },
  title: { color: colors.text, fontSize: 20, fontWeight: '800' },
  close: { color: colors.muted, fontSize: 22, padding: 4 },
  body: { padding: 18, paddingTop: 8 },
  subtitle: { color: colors.muted, fontSize: 14, marginBottom: 14, lineHeight: 20 },
  photo: { width: '100%', height: 180, borderRadius: radius.md, marginBottom: 14, backgroundColor: colors.card },
  center: { alignItems: 'center', paddingVertical: 18 },
  muted: { color: colors.muted, fontSize: 13, marginTop: 4 },
  resultCard: { backgroundColor: colors.card, borderRadius: radius.md, padding: 14, marginBottom: 14 },
  alertBox: { borderWidth: 2, borderRadius: radius.md, padding: 12, marginBottom: 10 },
  alertText: { color: colors.text, fontSize: 16, fontWeight: '700', lineHeight: 22 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6 },
  rowLabel: { color: colors.muted, fontSize: 14 },
  rowValue: { color: colors.text, fontSize: 14, fontWeight: '600', textTransform: 'capitalize', flexShrink: 1, textAlign: 'right', marginLeft: 12 },
  errorBox: { backgroundColor: colors.card, borderRadius: radius.md, padding: 14, marginBottom: 14, borderWidth: 1, borderColor: colors.danger },
  errorText: { color: colors.text, fontSize: 14, lineHeight: 20 },
  link: { color: colors.accent, fontWeight: '700', marginTop: 8 },
  shareRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 16 },
  shareTitle: { color: colors.text, fontSize: 15, fontWeight: '700' },
  primary: { backgroundColor: colors.accent, borderRadius: radius.md, paddingVertical: 14, alignItems: 'center' },
  primaryText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  disabled: { opacity: 0.5 },
});
