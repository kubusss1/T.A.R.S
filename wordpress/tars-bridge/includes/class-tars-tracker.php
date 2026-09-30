<?php
/**
 * Front-end: dołączenie skryptu śledzącego odsłony i zgody.
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Ładuje assets/tars-track.js na stronach publicznych.
 */
final class TARS_Bridge_Tracker {

	/**
	 * Podpina hooki.
	 */
	public static function register() {
		add_action( 'wp_enqueue_scripts', array( __CLASS__, 'enqueue' ) );
	}

	/**
	 * Czy śledzić bieżące żądanie.
	 *
	 * @return bool
	 */
	public static function should_track() {
		$settings = TARS_Bridge_DB::settings();
		$track    = ! empty( $settings['tracking'] );

		if ( is_admin() || is_feed() || is_preview() || is_customize_preview() || is_robots() || is_trackback() ) {
			$track = false;
		}
		if ( is_user_logged_in() && current_user_can( 'manage_options' ) ) {
			$track = false; // Pomijamy administratorów.
		}
		$ua = isset( $_SERVER['HTTP_USER_AGENT'] ) ? sanitize_text_field( wp_unslash( $_SERVER['HTTP_USER_AGENT'] ) ) : ''; // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized
		if ( TARS_Logic::is_bot( $ua ) ) {
			$track = false;
		}

		/**
		 * Pozwala wyłączyć/włączyć śledzenie dla bieżącego widoku.
		 *
		 * @param bool $track Czy śledzić.
		 */
		return (bool) apply_filters( 'tars_bridge_should_track', $track );
	}

	/**
	 * Kolejkuje skrypt z konfiguracją.
	 */
	public static function enqueue() {
		if ( ! self::should_track() ) {
			return;
		}
		$settings = TARS_Bridge_DB::settings();
		wp_enqueue_script(
			'tars-bridge-track',
			TARS_BRIDGE_URL . 'assets/tars-track.js',
			array(),
			TARS_BRIDGE_VERSION,
			array(
				'in_footer' => true,
				'strategy'  => 'defer',
			)
		);
		$config = array(
			'hit'     => esc_url_raw( rest_url( TARS_Bridge_REST::NAMESPACE_V1 . '/hit' ) ),
			'consent' => esc_url_raw( rest_url( TARS_Bridge_REST::NAMESPACE_V1 . '/consent' ) ),
			'dnt'     => ! empty( $settings['respect_dnt'] ),
		);
		wp_add_inline_script( 'tars-bridge-track', 'window.tarsBridge = ' . wp_json_encode( $config ) . ';', 'before' );
	}
}
