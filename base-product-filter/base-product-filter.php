<?php
/**
 * Plugin Name: BASE Product Filter (完全版)
 * Description: BASEの商品をボタンで絞り込み表示（BASE API連携）
 * Version: 2.0.0
 * Author: Your Name
 */

if (!defined('ABSPATH')) {
    exit;
}

// BASE API URL
define('BASE_API_URL', 'https://api.thebase.in/1/');
define('CACHE_DURATION', 43200); // 12時間キャッシュ（速度改善）
define('OBJECT_CACHE_GROUP', 'base_products'); // オブジェクトキャッシュグループ

/**
 * 設定確認
 */
function base_check_config() {
    return defined('BASE_CLIENT_ID') && 
           defined('BASE_CLIENT_SECRET') && 
           defined('BASE_SHOP_ID') &&
           !empty(BASE_CLIENT_ID) &&
           !empty(BASE_CLIENT_SECRET);
}

/**
 * BASE認証URL取得
 */
function base_get_auth_url() {
    $callback = admin_url('admin.php?page=base-auth-callback');
    return 'https://api.thebase.in/1/oauth/authorize?' . http_build_query(array(
        'response_type' => 'code',
        'client_id' => BASE_CLIENT_ID,
        'redirect_uri' => $callback,
        'scope' => 'read_items',
        'state' => wp_create_nonce('base_oauth'),
    ));
}

/**
 * BASE OAuth アクセストークン取得（認証コードから）
 */
function base_get_access_token($force = false) {
    if (!base_check_config()) {
        set_transient('base_last_error', '設定が不完全です', 60);
        return false;
    }
    
    // 保存されているトークンを確認
    $saved_token = get_option('base_access_token');
    $expires_at = get_option('base_token_expires_at', 0);
    
    if (!$force && $saved_token && time() < $expires_at) {
        return $saved_token;
    }
    
    // リフレッシュトークンで更新
    $refresh_token = get_option('base_refresh_token');
    if ($refresh_token) {
        $new_token = base_refresh_access_token($refresh_token);
        if ($new_token) {
            return $new_token;
        }
    }
    
    // トークンがない場合は再認証が必要
    set_transient('base_last_error', 'BASE認証が必要です。「BASE連携」ボタンをクリックしてください。', 60);
    return false;
}

/**
 * リフレッシュトークンで更新
 */
function base_refresh_access_token($refresh_token) {
    $callback = admin_url('admin.php?page=base-auth-callback');
    
    $response = wp_remote_post('https://api.thebase.in/1/oauth/token', array(
        'headers' => array(
            'Content-Type' => 'application/x-www-form-urlencoded',
        ),
        'body' => http_build_query(array(
            'grant_type' => 'refresh_token',
            'client_id' => BASE_CLIENT_ID,
            'client_secret' => BASE_CLIENT_SECRET,
            'refresh_token' => $refresh_token,
            'redirect_uri' => $callback,
        )),
        'timeout' => 30,
    ));
    
    if (is_wp_error($response)) {
        return false;
    }
    
    $body = json_decode(wp_remote_retrieve_body($response), true);
    
    if (!empty($body['access_token'])) {
        update_option('base_access_token', $body['access_token']);
        update_option('base_token_expires_at', time() + (isset($body['expires_in']) ? $body['expires_in'] - 60 : 86400));
        if (!empty($body['refresh_token'])) {
            update_option('base_refresh_token', $body['refresh_token']);
        }
        delete_transient('base_last_error');
        return $body['access_token'];
    }
    
    return false;
}

/**
 * 認証コードをアクセストークンに交換
 */
function base_exchange_code_for_token($code) {
    $callback = admin_url('admin.php?page=base-auth-callback');
    
    $response = wp_remote_post('https://api.thebase.in/1/oauth/token', array(
        'headers' => array(
            'Content-Type' => 'application/x-www-form-urlencoded',
        ),
        'body' => http_build_query(array(
            'grant_type' => 'authorization_code',
            'client_id' => BASE_CLIENT_ID,
            'client_secret' => BASE_CLIENT_SECRET,
            'code' => $code,
            'redirect_uri' => $callback,
        )),
        'timeout' => 30,
    ));
    
    if (is_wp_error($response)) {
        $error_msg = 'OAuth通信エラー: ' . $response->get_error_message();
        set_transient('base_last_error', $error_msg, 60);
        return false;
    }
    
    $status_code = wp_remote_retrieve_response_code($response);
    $body = json_decode(wp_remote_retrieve_body($response), true);
    
    if ($status_code !== 200) {
        $error_msg = 'トークン取得失敗 (HTTP ' . $status_code . '): ' . wp_remote_retrieve_body($response);
        set_transient('base_last_error', $error_msg, 60);
        return false;
    }
    
    if (empty($body['access_token'])) {
        $error_msg = 'アクセストークンが取得できませんでした: ' . print_r($body, true);
        set_transient('base_last_error', $error_msg, 60);
        return false;
    }
    
    // トークンを保存
    update_option('base_access_token', $body['access_token']);
    update_option('base_token_expires_at', time() + (isset($body['expires_in']) ? $body['expires_in'] - 60 : 86400));
    if (!empty($body['refresh_token'])) {
        update_option('base_refresh_token', $body['refresh_token']);
    }
    delete_transient('base_last_error');
    delete_transient('base_products'); // キャッシュクリア
    
    return $body['access_token'];
}

/**
 * フィルター定義（辞書）
 */
function base_get_filter_definitions() {
    return array(
        "brand" => array(
            "Ambient" => array("Ambient", "アンビエント"),
            "an Andy" => array("an", "アン"),
            "Andy" => array("Andy", "アンディ"),
            "AR Angel R" => array("AR Angel R", "Angel R", "AR", "エンジェルアール"),
            "BayBClub" => array("BayBClub", "ベイビークラブ"),
            "cherrykeke" => array("cherrykeke", "チェリーケケ"),
            "Ck Calvinklein" => array("Ck Calvinklein", "Calvin Klein", "カルバンクライン"),
            "COCO&YUKA" => array("COCO&YUKA"),
            "dazzy lounge" => array("dazzy lounge", "デイジーラウンジ"),
            "dazzy queen" => array("dazzy queen", "デイジークイーン"),
            "dazzy store" => array("dazzy store", "デイジーストア"),
            "DAZZY" => array("DAZZY", "デイジー"),
            "DEA by ROBE de FLEURS" => array("DEA by ROBE de FLEURS", "ディアバイローブドフルール"),
            "EmiriaWiz" => array("EmiriaWiz", "エミリアウィズ"),
            "ERUKEI" => array("ERUKEI", "エルケイ"),
            "EauSouage" => array("EauSouage"),
            "FEIMAN" => array("FEIMAN", "フェイマン"),
            "GINZA COUTURE ERUKEI" => array("GINZA COUTURE ERUKEI", "GINZA COUTURE", "エルケイ"),
            "GLAMOROUS by Andy" => array("GLAMOROUS by Andy", "グラマラスバイアンディ"),
            "GRACE" => array("GRACE", "グレース", "グレイス"),
            "GRAXIA" => array("GRAXIA"),
            "GRL" => array("GRL", "グレイル"),
            "H&M" => array("H&M", "エイチアンドエム"),
            "han queen" => array("han queen"),
            "IRMA" => array("IRMA", "イルマ"),
            "JEAN MACLEAN" => array("JEAN MACLEAN", "ジャンマクレーン"),
            "JEWELS" => array("JEWELS", "ジュエルズ"),
            "LIPSY LONDON" => array("LIPSY LONDON", "リプシーロンドン"),
            "Love Rich" => array("Love Rich", "ラブリッチ"),
            "PEARL" => array("PEARL", "パール"),
            "Randy" => array("Randy", "ランディ"),
            "RESEXXY" => array("RESEXXY", "リゼクシー"),
            "Rinfarre" => array("Rinfarre", "リンファーレ"),
            "RINASCIMENTO" => array("RINASCIMENTO", "リナシメント"),
            "ROBE de FLEURS" => array("ROBE de FLEURS", "ローブドフルール"),
            "ROBE de FLEURS Glossy" => array("ROBE de FLEURS Glossy", "ローブドフルールグロッシー"),
            "Ryuyu" => array("Ryuyu", "リューユ"),
            "Ryuyu Chick" => array("Ryuyu Chick", "リューユチック"),
            "SATURDAY CLUB" => array("SATURDAY CLUB", "サタデークラブ"),
            "Settan ERUKEI" => array("Settan ERUKEI", "Settan", "セッタン"),
            "Tiara" => array("Tiara", "ティアラ"),
            "Tika" => array("Tika", "ティカ"),
            "Tika holic" => array("Tika holic", "ティカホリック"),
            "Trinity" => array("Trinity", "トリニティ"),
            "Vanessa Heart" => array("Vanessa Heart", "ヴァネッサハート"),
            "Veautt" => array("Veautt", "ヴュート"),
            "ZARA" => array("ZARA", "ザラ"),
            "その他" => array("その他")
        ),
        "color" => array(
            "ブラック" => array("ブラック", "黒"),
            "ホワイト" => array("ホワイト", "白"),
            "グレー" => array("グレー", "灰色", "グレイ"),
            "ベージュ" => array("ベージュ"),
            "ブラウン" => array("ブラウン", "茶色"),
            "レッド" => array("レッド", "赤"),
            "ピンク" => array("ピンク", "桃色"),
            "パープル" => array("パープル", "紫"),
            "ネイビー" => array("ネイビー", "紺"),
            "ブルー" => array("ブルー", "青"),
            "グリーン" => array("グリーン", "緑"),
            "カーキ" => array("カーキ"),
            "イエロー" => array("イエロー", "黄色"),
            "オレンジ" => array("オレンジ", "橙色"),
            "ゴールド" => array("ゴールド", "金色"),
            "シルバー" => array("シルバー", "銀色")
        ),
        "size" => array(
            "XS" => array("XS"),
            "S" => array("S"),
            "M" => array("M"),
            "L" => array("L"),
            "XL" => array("XL"),
            "FREE" => array("FREE", "フリー", "F")
        ),
        "length" => array("ロング","ミディ","ミニ"),
    );
}

/**
 * 商品データ加工（属性抽出）
 */
function base_enrich_product($p) {
    $dict = base_get_filter_definitions();
    $title = isset($p['title']) ? $p['title'] : '';
    $desc = isset($p['description']) ? $p['description'] : '';
    
    // 検索対象テキスト（タイトル + 説明文）
    $search_text = $title . "\n" . $desc;

    // ブランド抽出（最長一致優先、タイトル優先）
    $p['brand'] = null;
    $max_length = 0;
    $matched_in_title = false;
    
    // ステップ1: タイトル内で辞書とマッチするか確認
    foreach ($dict['brand'] as $canonical => $keywords) {
        // 「その他」はスキップ（最後に設定）
        if ($canonical === 'その他' || empty($keywords)) continue;
        
        foreach ($keywords as $k) {
            $matched = false;
            
            // 英数字のキーワードは単語境界を考慮、日本語はそのまま部分一致
            if (preg_match('/[a-zA-Z0-9]/', $k)) {
                // 英数字キーワード：単語境界を考慮（誤マッチ防止）
                if (preg_match('/\b'.preg_quote($k, '/').'\b/i', $title)) {
                    $matched = true;
                }
            } else {
                // 日本語キーワード：部分一致
                if (mb_strpos($title, $k) !== false) {
                    $matched = true;
                }
            }
            
            // タイトル内でマッチした場合、より長いキーワードを優先
            if ($matched && mb_strlen($k) > $max_length) {
                $p['brand'] = $canonical;
                $max_length = mb_strlen($k);
                $matched_in_title = true;
            }
        }
    }
    
    // ステップ2: タイトルでマッチがあれば確定
    if ($matched_in_title) {
        // タイトルでブランドが見つかったので、これを採用
    } else {
        // ステップ3: タイトルに未登録のブランド名があるか、品番構造をチェック
        // 品番（数字）で始まるタイトルの場合
        if (preg_match('/^\s*\d+\s/', $title)) {
            // タイトルが品番（数字）で始まる場合は「その他」として確定
            // 理由: 品番がある場合、ブランド名は品番直後に記載されるべき
            //       品番の後が英単語なら未登録ブランド、日本語ならブランド名なし
            //       いずれにしても説明文からブランドを拾うべきではない
            $p['brand'] = 'その他';
        } else if (preg_match('/\b([A-Z][a-zA-Z]{2,})\b/', $title, $matches)) {
            // 品番なしで大文字で始まる英単語がある → 未登録ブランドとして「その他」
            $p['brand'] = 'その他';
        } else {
            // ステップ4: 説明文で辞書とマッチするか確認
            $max_length = 0;
            foreach ($dict['brand'] as $canonical => $keywords) {
                // 「その他」はスキップ
                if ($canonical === 'その他' || empty($keywords)) continue;
                
                foreach ($keywords as $k) {
                    $matched = false;
                    
                    // 英数字のキーワードは単語境界を考慮、日本語はそのまま部分一致
                    if (preg_match('/[a-zA-Z0-9]/', $k)) {
                        if (preg_match('/\b'.preg_quote($k, '/').'\b/i', $desc)) {
                            $matched = true;
                        }
                    } else {
                        if (mb_strpos($desc, $k) !== false) {
                            $matched = true;
                        }
                    }
                    
                    // 説明文内でマッチした場合、より長いキーワードを優先
                    if ($matched && mb_strlen($k) > $max_length) {
                        $p['brand'] = $canonical;
                        $max_length = mb_strlen($k);
                    }
                }
            }
            
            // ステップ5: それでもマッチしない場合は「その他」
            if ($p['brand'] === null) {
                $p['brand'] = 'その他';
            }
        }
    }

    // カラー抽出（ブランドと同じ構造で処理）
    $p['colors'] = array();
    foreach ($dict['color'] as $canonical => $keywords) {
        foreach ($keywords as $k) {
            if (mb_strpos($search_text, $k) !== false) {
                $p['colors'][] = $canonical;
                break; // マッチしたら次の色へ
            }
        }
    }
    $p['colors'] = array_unique($p['colors']); // 重複除去

    // サイズ抽出（ブランドと同じ構造に変更）
    $p['size'] = null;
    foreach ($dict['size'] as $canonical => $keywords) {
        foreach ($keywords as $k) {
            // サイズは全文検索またはパターンマッチ
            if (preg_match('/[\s\(\[\{]'.preg_quote($k, '/').'[\s\)\]\}]/i', ' '.$search_text.' ') || 
                preg_match('/サイズ[:：\s]*'.preg_quote($k, '/').'/i', $search_text)) {
                $p['size'] = $canonical;
                break 2; // マッチしたら終了
            }
        }
    }

    // 丈抽出
    $p['length'] = array();
    foreach ($dict['length'] as $len) {
        if (mb_strpos($search_text, $len) !== false) {
            $p['length'][] = $len;
        }
    }
    $p['length'] = array_unique($p['length']); // 重複除去

    return $p;
}

/**
 * BASE API 商品一覧取得（高速化：二重キャッシュ）
 */
function base_get_products($force = false) {
    $cache_key = 'base_products';
    
    if (!$force) {
        // オブジェクトキャッシュを先にチェック（超高速）
        $cached = wp_cache_get($cache_key, OBJECT_CACHE_GROUP);
        if ($cached !== false) {
            return $cached;
        }
        
        // Transientキャッシュをチェック（高速）
        $cached = get_transient($cache_key);
        if ($cached) {
            // オブジェクトキャッシュにも保存
            wp_cache_set($cache_key, $cached, OBJECT_CACHE_GROUP, CACHE_DURATION);
            return $cached;
        }
    }
    
    $token = base_get_access_token($force);
    if (!$token) {
        set_transient('base_last_error', 'アクセストークンの取得に失敗しました', 60);
        return array();
    }
    
    // 全商品取得のためのループ処理
    $all_items = array();
    $offset = 0;
    $limit = 100; // 1回あたりの最大取得数（BASE APIの上限付近）

    while (true) {
        $api_url = add_query_arg(array(
            'limit' => $limit,
            'offset' => $offset,
        ), BASE_API_URL . 'items');

        $response = wp_remote_get($api_url, array(
            'headers' => array(
                'Authorization' => 'Bearer ' . $token,
            ),
            'timeout' => 30,
        ));
        
        if (is_wp_error($response)) {
            $error_msg = 'API通信エラー: ' . $response->get_error_message();
            set_transient('base_last_error', $error_msg, 60);
            error_log('BASE API Error: ' . $response->get_error_message());
            break;
        }
        
        $status_code = wp_remote_retrieve_response_code($response);
        $body = json_decode(wp_remote_retrieve_body($response), true);
        
        if ($status_code !== 200) {
            $error_msg = 'API取得失敗 (HTTP ' . $status_code . '): ' . wp_remote_retrieve_body($response);
            set_transient('base_last_error', $error_msg, 60);
            error_log('BASE API Error: ' . $error_msg);
            break;
        }
        
        if (empty($body['items'])) {
            break;
        }

        $all_items = array_merge($all_items, $body['items']);

        // 取得件数がlimit未満なら、これ以上商品はないので終了
        if (count($body['items']) < $limit) {
            break;
        }
        
        $offset += $limit;
        usleep(200000); // API負荷軽減のため0.2秒待機
    }

    if (empty($all_items)) {
        if (!get_transient('base_last_error')) {
            set_transient('base_last_error', '商品データが空です。BASEショップに商品が登録されているか確認してください。', 60);
        }
        return array();
    }
    
    $products = array();
    $seen_ids = array(); // 重複チェック用
    
    foreach ($all_items as $item) {
        $item_id = isset($item['item_id']) ? $item['item_id'] : '';
        
        // 重複チェック：同じIDの商品はスキップ
        if (in_array($item_id, $seen_ids)) {
            continue;
        }
        $seen_ids[] = $item_id;
        
        $products[] = array(
            'id' => $item_id,
            'title' => isset($item['title']) ? $item['title'] : '',
            'price' => isset($item['price']) ? intval($item['price']) : 0,
            'description' => isset($item['detail']) ? $item['detail'] : '',
            'image' => isset($item['img1_origin']) ? $item['img1_origin'] : '',
            'thumbnail' => isset($item['img1_250']) ? $item['img1_250'] : '',
            'url' => 'https://' . BASE_SHOP_ID . '.base.shop/items/' . $item_id,
            'stock' => isset($item['stock']) ? intval($item['stock']) : 0,
            'visible' => isset($item['visible']) ? intval($item['visible']) : 1,
        );
        
        // 属性情報を付与
        $products[count($products)-1] = base_enrich_product($products[count($products)-1]);
    }
    
    delete_transient('base_last_error');
    // 二重キャッシュで高速化
    set_transient($cache_key, $products, CACHE_DURATION);
    wp_cache_set($cache_key, $products, OBJECT_CACHE_GROUP, CACHE_DURATION);
    
    return $products;
}

/**
 * 管理画面メニュー
 */
add_action('admin_menu', function() {
    add_menu_page(
        'BASE商品',
        'BASE商品',
        'manage_options',
        'base-product-filter',
        'base_admin_page',
        'dashicons-cart',
        30
    );
    
    // 認証コールバック用（非表示）
    add_submenu_page(
        null,
        'BASE認証コールバック',
        'BASE認証コールバック',
        'manage_options',
        'base-auth-callback',
        'base_auth_callback_page'
    );
});

/**
 * 管理画面ページ
 */
function base_admin_page() {
    if (isset($_POST['refresh_cache'])) {
        delete_transient('base_products');
        wp_cache_delete('base_products', OBJECT_CACHE_GROUP);
        echo '<div class="notice notice-success"><p>キャッシュを更新しました（二重キャッシュもクリア）</p></div>';
    }
    
    if (isset($_POST['disconnect_base'])) {
        delete_option('base_access_token');
        delete_option('base_refresh_token');
        delete_option('base_token_expires_at');
        delete_transient('base_products');
        wp_cache_delete('base_products', OBJECT_CACHE_GROUP);
        echo '<div class="notice notice-success"><p>BASE連携を解除しました</p></div>';
    }
    
    $config_ok = base_check_config();
    $products = $config_ok ? base_get_products() : array();
    ?>
    <div class="wrap">
        <h1>🛒 BASE Product Filter</h1>
        
        <?php if (!$config_ok): ?>
            <div class="notice notice-warning">
                <h2>⚠️ 設定が必要です</h2>
                <p><strong>wp-config.php</strong> に以下を追加してください：</p>
                <pre style="background:#f5f5f5;padding:15px;">
// BASE API 設定
define('BASE_CLIENT_ID', 'your_client_id');
define('BASE_CLIENT_SECRET', 'your_client_secret');
define('BASE_SHOP_ID', 'yourshop');</pre>
            </div>
        <?php else: ?>
            <?php
            $has_token = get_option('base_access_token') && time() < get_option('base_token_expires_at', 0);
            ?>
            
            <div class="notice notice-success">
                <p>✅ 設定完了</p>
            </div>
            
            <?php if (!$has_token): ?>
                <div class="notice notice-warning">
                    <h2>🔐 BASE認証が必要です</h2>
                    <p>初回のみBASEとの連携認証が必要です。以下のボタンをクリックしてBASEにログインしてください。</p>
                    <a href="<?php echo esc_url(base_get_auth_url()); ?>" class="button button-primary button-large">
                        🔗 BASEと連携する
                    </a>
                </div>
            <?php else: ?>
                <div class="notice notice-success">
                    <p>✅ BASE認証済み（有効期限: <?php echo date('Y-m-d H:i:s', get_option('base_token_expires_at', 0)); ?>）</p>
                </div>
            <?php endif; ?>
            
            <?php
            // デバッグ情報
            $token = base_get_access_token();
            $debug_info = array(
                'token' => $token ? '取得成功' : '取得失敗',
                'client_id' => substr(BASE_CLIENT_ID, 0, 8) . '...',
                'shop_id' => BASE_SHOP_ID,
            );
            
            // API直接テスト
            if ($token && isset($_GET['debug'])) {
                $api_response = wp_remote_get(BASE_API_URL . 'items', array(
                    'headers' => array(
                        'Authorization' => 'Bearer ' . $token,
                    ),
                ));
                $debug_info['api_code'] = wp_remote_retrieve_response_code($api_response);
                $debug_info['api_body'] = wp_remote_retrieve_body($api_response);
            }
            ?>
            
            <div class="card" style="max-width:800px;margin-top:20px;">
                <h2>📦 商品データ</h2>
                <p>取得商品数: <strong><?php echo count($products); ?> 件</strong></p>
                
                <?php 
                $last_error = get_transient('base_last_error');
                if ($last_error): 
                ?>
                    <div class="notice notice-error" style="margin-top:10px;">
                        <p><strong>❌ エラー詳細：</strong></p>
                        <pre style="background:#fff;padding:10px;overflow:auto;white-space:pre-wrap;"><?php echo esc_html($last_error); ?></pre>
                    </div>
                <?php endif; ?>
                
                <?php if (isset($_GET['debug'])): ?>
                    <div style="background:#f9f9f9;padding:10px;margin:10px 0;">
                        <strong>🔍 デバッグ情報：</strong><br>
                        <?php foreach ($debug_info as $key => $val): ?>
                            <div><code><?php echo $key; ?>:</code> <?php echo is_string($val) ? esc_html($val) : '<pre>' . esc_html(print_r($val, true)) . '</pre>'; ?></div>
                        <?php endforeach; ?>
                    </div>
                <?php endif; ?>
                
                <form method="post" style="display:inline-block;margin-right:10px;">
                    <button type="submit" name="refresh_cache" class="button button-primary">🔄 キャッシュを更新</button>
                </form>
                <p class="description" style="display:inline-block;">※キャッシュ: 12時間（速度最適化済み）</p>
                <a href="?page=base-product-filter&debug=1" class="button">🔍 デバッグモード</a>
                
                <?php if ($has_token): ?>
                    <form method="post" style="display:inline-block;margin-left:10px;" onsubmit="return confirm('BASE連携を解除しますか？再度連携するには認証が必要になります。');">
                        <button type="submit" name="disconnect_base" class="button button-secondary">🔓 BASE連携を解除</button>
                    </form>
                <?php endif; ?>
            </div>
            
            <div class="card" style="max-width:800px;margin-top:20px;">
                <h2>📝 使い方</h2>
                <p>固定ページに以下を追加：</p>
                <pre style="background:#f5f5f5;padding:15px;"><code>[base_products]</code></pre>
            </div>
        <?php endif; ?>
    </div>
    <?php
}

/**
 * フィルタリング用URL生成ヘルパー（複数選択トグル用）
 */
function base_get_toggle_link_url($param_key, $value) {
    // 現在のURLパラメータを取得
    $current_val_str = isset($_GET[$param_key]) ? sanitize_text_field($_GET[$param_key]) : '';
    // カンマ区切りを配列に分解
    $current_values = $current_val_str !== '' ? explode(',', $current_val_str) : array();
    
    // 値の存在確認
    $key = array_search((string)$value, $current_values, true);

    if ($key !== false) {
        // 存在すれば削除（選択解除）
        unset($current_values[$key]);
    } else {
        // 存在しなければ追加（選択）
        $current_values[] = (string)$value;
    }

    // 配列をカンマ区切り文字列に戻す
    $new_param = implode(',', $current_values);

    // URL生成
    return $new_param === '' ? remove_query_arg($param_key) : add_query_arg($param_key, $new_param);
}

/**
 * ショートコード（高速化：HTTPヘッダーキャッシュ追加）
 */
add_shortcode('base_products', function($atts) {
    // HTTPキャッシュヘッダーを設定（ブラウザキャッシュで高速化）
    if (!headers_sent()) {
        header('Cache-Control: public, max-age=3600'); // 1時間ブラウザキャッシュ
        header('Expires: ' . gmdate('D, d M Y H:i:s', time() + 3600) . ' GMT');
    }
    
    if (!base_check_config()) {
        return '<div style="padding:20px;background:#fff3cd;border:1px solid #ffc107;border-radius:5px;">
            ⚠️ BASE Product Filter設定が必要です
        </div>';
    }
    
    $products = base_get_products();
    $dict = base_get_filter_definitions();
    
    // ショートコード属性のデフォルト値
    $atts = shortcode_atts(array(
        'brand' => null,
        'color' => null,
        'size' => null,
        'length' => null,
        'price_range' => null,
    ), $atts);
    
    // URLパラメータによるフィルタリング（カンマ区切りを配列化して複数選択に対応）
    $get_params = function($key) use ($atts) {
        // URLパラメータ優先、なければショートコード属性
        $val = isset($_GET[$key]) ? sanitize_text_field($_GET[$key]) : (isset($atts[$key]) ? $atts[$key] : null);
        if (empty($val)) return array();
        return explode(',', $val);
    };

    $filters = array(
        "brand"  => $get_params("brand"),
        "color"  => $get_params("color"),
        "size"   => $get_params("size"),
        "length" => $get_params("length"),
        "price_range" => isset($_GET["price_range"]) ? sanitize_text_field($_GET["price_range"]) : $atts['price_range'],
    );

    $products = array_filter($products, function($p) use ($filters) {
        // データが存在しない場合の初期値（エラー防止）
        $p_brand = isset($p["brand"]) ? $p["brand"] : null;
        $p_size = isset($p["size"]) ? $p["size"] : null;
        $p_colors = isset($p["colors"]) && is_array($p["colors"]) ? $p["colors"] : array();
        $p_length = isset($p["length"]) && is_array($p["length"]) ? $p["length"] : array();

        // ブランド (OR検索)
        if (!empty($filters["brand"]) && !in_array($p_brand, $filters["brand"])) return false;
        // サイズ (OR検索)
        if (!empty($filters["size"]) && !in_array($p_size, $filters["size"])) return false;
        // カラー (OR検索: 共通項がなければ除外)
        if (!empty($filters["color"]) && empty(array_intersect($p_colors, $filters["color"]))) return false;
        // 丈 (OR検索)
        if (!empty($filters["length"]) && empty(array_intersect($p_length, $filters["length"]))) return false;
        
        // 価格フィルタ（JS用互換）
        if (!empty($filters["price_range"]) && $filters["price_range"] !== 'all') {
            list($min, $max) = explode('-', $filters["price_range"]);
            if ($p['price'] < intval($min) || $p['price'] > intval($max)) return false;
        }
        
        return true;
    });
    
    // 現在のURL（パラメータなし）
    $base_url = strtok($_SERVER["REQUEST_URI"], '?');
    
    ob_start();
    ?>
    <div id="base-filter-app">
        <!-- BASE Filter Plugin: Start -->
        
        <style>
            /* 全体設定 */
            #base-filter-app { font-family: "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN", "Hiragino Sans", Meiryo, sans-serif; }
            
            /* WordPressページタイトル非表示 */
            .entry-title, h1.entry-title, .page-title, .wp-block-post-title { display: none !important; }
            
            /* WordPressフッター非表示 */
            .has-text-align-right { display: none !important; }
            
            /* フィルターセクション: 柔らかく上品に */
            .filter-section {display: block !important; margin-bottom: 40px; padding: 25px; background: #e5e4e0; border-radius: 16px; box-shadow: 0 5px 20px rgba(0,0,0,0.03); border: none;}
            .filter-group h4 {margin: 0 0 10px; font-size: 13px; color: #888; font-weight: 600; letter-spacing: 0.05em;}
            .filter-links {display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px;}
            
            /* フィルターリンク: 丸みのあるデザイン */
            .filter-link {
                text-decoration: none; 
                padding: 6px 16px; 
                border: 1px solid #eee; 
                border-radius: 20px; 
                font-size: 13px; 
                color: #666; 
                background: #fff; 
                transition: all 0.3s ease;
            }
            .filter-link:hover {
                background: #fdfdfd; 
                border-color: #ddd;
                transform: translateY(-1px);
            }
            .filter-link.active {
                background: #f8d7da; /* くすみピンク */
                color: #721c24; 
                border-color: #f5c6cb;
                font-weight: bold;
            }
            
            /* 商品グリッド：BASE風 */
            .products-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 24px;
                margin-top: 30px;
            }
            
            /* スマホ対応: 2列表示（BASEに近い） */
            @media (max-width: 768px) {
                .products-grid {
                    grid-template-columns: repeat(2, 1fr);
                    gap: 12px;
                }
                .product-info { padding: 12px; }
                .product-title { font-size: 13px; margin-bottom: 6px; }
                .product-price { font-size: 14px; }
                .product-badge { font-size: 12px; padding: 5px 10px; }
            }
            
            /* 商品カード: BASE風デザイン */
            .product-card {
                background: #e5e4e0;
                border-radius: 8px;
                overflow: hidden;
                transition: all 0.3s ease;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                border: 1px solid #e8e8e8;
            }
            .product-card:hover {
                transform: translateY(-3px);
                box-shadow: 0 8px 20px rgba(0,0,0,0.12);
                border-color: #ddd;
            }
            .product-main-link {
                display: block;
                text-decoration: none;
                color: inherit;
            }
            .product-main-link:hover .product-image {
                transform: scale(1.05);
            }
            
            /* 画像: 全体を表示 (contain) + Lazy Load対応 */
            .product-image-wrapper {
                width: 100%;
                height: 0;
                padding-bottom: 133%; /* 3:4 の比率で枠を確保 */
                position: relative;
                background: #e5e4e0;
                overflow: hidden;
            }
            .product-image {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                object-fit: contain; /* 画像全体を表示（欠けないように） */
                transition: transform 0.5s ease, opacity 0.3s ease;
                opacity: 0; /* Lazy Load用 */
            }
            .product-image.loaded {
                opacity: 1; /* 読み込み完了時に表示 */
            }

            
            /* 商品情報：BASE風 */
            .product-info {
                padding: 16px;
                text-align: left;
                background: #e5e4e0;
            }
            .product-title {
                font-size: 14px;
                line-height: 1.6;
                margin: 0 0 8px 0;
                color: #333;
                font-weight: 500;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
                min-height: 44px;
            }
            .product-price {
                font-size: 18px;
                font-weight: bold;
                color: #333;
                margin: 8px 0;
            }

            .product-meta {
                display: flex;
                gap: 8px;
                margin-top: 8px;
                flex-wrap: wrap;
            }
            .product-badge {
                display: inline-block;
                font-size: 13px;
                padding: 6px 12px;
                border-radius: 6px;
                background: #f5f5f5;
                color: #666;
                text-decoration: none;
                transition: all 0.2s ease;
            }
            .product-badge:hover {
                background: #e8e8e8;
                color: #333;
                transform: translateY(-1px);
            }
        </style>
        
        <div class="filter-section">
            <h3>🔍 条件で絞り込み</h3>
            
            <div class="filter-group">
                <h4>ブランド</h4>
                <div class="filter-links">
                    <?php foreach ($dict['brand'] as $canonical => $keywords): ?>
                        <?php $is_active = in_array($canonical, $filters['brand']); ?>
                        <a href="<?php echo esc_url(base_get_toggle_link_url('brand', $canonical)); ?>" class="filter-link <?php echo $is_active ? 'active' : ''; ?>">
                            <?php echo esc_html($keywords[0]); // 代表名を表示 ?>
                        </a>
                    <?php endforeach; ?>
                </div>
            </div>

            <div class="filter-group">
                <h4>カラー</h4>
                <div class="filter-links">
                    <?php foreach ($dict['color'] as $canonical => $keywords): ?>
                        <?php $is_active = in_array($canonical, $filters['color']); ?>
                        <a href="<?php echo esc_url(base_get_toggle_link_url('color', $canonical)); ?>" class="filter-link <?php echo $is_active ? 'active' : ''; ?>"><?php echo esc_html($keywords[0]); // 代表名を表示 ?></a>
                    <?php endforeach; ?>
                </div>
            </div>

            <div class="filter-group">
                <h4>サイズ</h4>
                <div class="filter-links">
                    <?php foreach ($dict['size'] as $canonical => $keywords): ?>
                        <?php $is_active = in_array($canonical, $filters['size']); ?>
                        <a href="<?php echo esc_url(base_get_toggle_link_url('size', $canonical)); ?>" class="filter-link <?php echo $is_active ? 'active' : ''; ?>"><?php echo esc_html($keywords[0]); // 代表名を表示 ?></a>
                    <?php endforeach; ?>
                </div>
            </div>
            
            <div class="filter-group">
                <?php 
                // フィルタが一つでも適用されているかチェック
                $has_filters = !empty($filters['brand']) || !empty($filters['color']) || !empty($filters['size']) || !empty($filters['length']);
                if($has_filters): 
                ?>
                    <a href="<?php echo esc_url(strtok($_SERVER["REQUEST_URI"], '?')); ?>" class="button">× 条件をクリア</a>
                <?php endif; ?>
            </div>
        </div>
        
        <div class="products-grid" id="products-grid">
            <?php if (empty($products)): ?>
                <p style="grid-column:1/-1;text-align:center;padding:40px;">商品がありません</p>
            <?php else: ?>
                <?php foreach ($products as $p): ?>
                    <div class="product-card" data-price="<?php echo esc_attr($p['price']); ?>">
                        <a href="<?php echo esc_url($p['url']); ?>" class="product-main-link">
                            <div class="product-image-wrapper">
                                <img 
                                    data-src="<?php echo esc_url($p['thumbnail'] ?: $p['image']); ?>" 
                                    src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" 
                                    class="product-image lazy" 
                                    alt="<?php echo esc_attr($p['title']); ?>"
                                    loading="lazy"
                                >
                            </div>
                            <div class="product-info">
                                <h3 class="product-title"><?php echo esc_html($p['title']); ?></h3>
                                <p class="product-price">¥<?php echo number_format($p['price']); ?></p>
                            </div>
                        </a>
                        
                        <?php if (!empty($p['brand']) || !empty($p['size']) || !empty($p['colors'])): ?>
                            <div class="product-info" style="padding-top: 0;">
                                <div class="product-meta">
                                    <?php if (!empty($p['brand'])): ?>
                                        <a href="<?php echo esc_url(base_get_toggle_link_url('brand', $p['brand'])); ?>" class="product-badge"><?php echo esc_html($p['brand']); ?></a>
                                    <?php endif; ?>
                                    <?php if (!empty($p['size'])): ?>
                                        <a href="<?php echo esc_url(base_get_toggle_link_url('size', $p['size'])); ?>" class="product-badge">サイズ: <?php echo esc_html($p['size']); ?></a>
                                    <?php endif; ?>
                                    <?php if (!empty($p['colors'])): ?>
                                        <?php foreach (array_slice($p['colors'], 0, 2) as $color): ?>
                                            <a href="<?php echo esc_url(base_get_toggle_link_url('color', $color)); ?>" class="product-badge"><?php echo esc_html($color); ?></a>
                                        <?php endforeach; ?>
                                    <?php endif; ?>
                                </div>
                            </div>
                        <?php endif; ?>
                    </div>
                <?php endforeach; ?>
            <?php endif; ?>
        </div>
    </div>
    
    <!-- 高速化: Lazy Load + Intersection Observer -->
    <script>
    (function() {
        'use strict';
        
        // Intersection Observerで画像を遅延読み込み（パフォーマンス向上）
        if ('IntersectionObserver' in window) {
            const imageObserver = new IntersectionObserver(function(entries, observer) {
                entries.forEach(function(entry) {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        const src = img.getAttribute('data-src');
                        if (src) {
                            img.src = src;
                            img.classList.add('loaded');
                            img.classList.remove('lazy');
                            imageObserver.unobserve(img);
                        }
                    }
                });
            }, {
                rootMargin: '50px 0px', // 50px手前から読み込み開始
                threshold: 0.01
            });
            
            // すべてのlazy画像を監視
            document.querySelectorAll('.product-image.lazy').forEach(function(img) {
                imageObserver.observe(img);
            });
        } else {
            // Intersection Observer非対応ブラウザ用のフォールバック
            document.querySelectorAll('.product-image.lazy').forEach(function(img) {
                const src = img.getAttribute('data-src');
                if (src) {
                    img.src = src;
                    img.classList.add('loaded');
                }
            });
        }
    })();
    </script>
    <?php
    return ob_get_clean();
});

/**
 * BASE認証コールバックページ
 */
function base_auth_callback_page() {
    if (!current_user_can('manage_options')) {
        wp_die('権限がありません');
    }
    
    // stateの検証
    if (!isset($_GET['state']) || !wp_verify_nonce($_GET['state'], 'base_oauth')) {
        wp_die('不正なリクエストです');
    }
    
    // エラーチェック
    if (isset($_GET['error'])) {
        $error = sanitize_text_field($_GET['error']);
        $error_desc = isset($_GET['error_description']) ? sanitize_text_field($_GET['error_description']) : '';
        ?>
        <div class="wrap">
            <h1>❌ BASE認証失敗</h1>
            <div class="notice notice-error">
                <p><strong>エラー:</strong> <?php echo esc_html($error); ?></p>
                <?php if ($error_desc): ?>
                    <p><?php echo esc_html($error_desc); ?></p>
                <?php endif; ?>
            </div>
            <a href="<?php echo admin_url('admin.php?page=base-product-filter'); ?>" class="button button-primary">戻る</a>
        </div>
        <?php
        return;
    }
    
    // 認証コード取得
    if (!isset($_GET['code'])) {
        wp_die('認証コードが見つかりません');
    }
    
    $code = sanitize_text_field($_GET['code']);
    $token = base_exchange_code_for_token($code);
    
    if ($token) {
        ?>
        <div class="wrap">
            <h1>✅ BASE認証成功</h1>
            <div class="notice notice-success">
                <p>BASEとの連携が完了しました！</p>
            </div>
            <script>
                setTimeout(function(){
                    window.location.href = '<?php echo admin_url('admin.php?page=base-product-filter'); ?>';
                }, 2000);
            </script>
            <p>自動的にリダイレクトされます...</p>
            <a href="<?php echo admin_url('admin.php?page=base-product-filter'); ?>" class="button button-primary">BASE商品管理に戻る</a>
        </div>
        <?php
    } else {
        $error = get_transient('base_last_error');
        ?>
        <div class="wrap">
            <h1>❌ トークン取得失敗</h1>
            <div class="notice notice-error">
                <p>アクセストークンの取得に失敗しました。</p>
                <?php if ($error): ?>
                    <pre><?php echo esc_html($error); ?></pre>
                <?php endif; ?>
            </div>
            <a href="<?php echo admin_url('admin.php?page=base-product-filter'); ?>" class="button button-primary">戻る</a>
        </div>
        <?php
    }
}
