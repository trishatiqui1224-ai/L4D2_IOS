#pragma once

#import <Foundation/Foundation.h>

namespace l4d2::i18n {

enum class Language {
    English,
    Portuguese,
    Spanish
};

inline NSString* GetText(NSString* key, Language lang) {
    static NSDictionary<NSString*, NSDictionary<NSNumber*, NSString*>*>* strings = @{
        @"app_title": @{
            @(0): @"Left 4 Dead 2 Recomp",
            @(1): @"Left 4 Dead 2 Recomp",
            @(2): @"Left 4 Dead 2 Recomp"
        },
        @"verified_disc": @{
            @(0): @"Verified: Title 454108D4 • Media 0E79403B",
            @(1): @"Verificado: Título 454108D4 • Mídia 0E79403B",
            @(2): @"Verificado: Título 454108D4 • Disco 0E79403B"
        },
        @"unverified_disc": @{
            @(0): @"No Disc Imported",
            @(1): @"Nenhum Disco Importado",
            @(2): @"Ningún Disco Importado"
        },
        @"btn_play": @{
            @(0): @"PLAY CAMPAIGN",
            @(1): @"JOGAR CAMPANHA",
            @(2): @"JUGAR CAMPAÑA"
        },
        @"btn_import": @{
            @(0): @"Import ISO / Folder",
            @(1): @"Importar ISO / Pasta",
            @(2): @"Importar ISO / Carpeta"
        },
        @"btn_verify": @{
            @(0): @"Verify Disc (SHA-256)",
            @(1): @"Verificar Disco (SHA-256)",
            @(2): @"Verificar Disco (SHA-256)"
        },
        @"verifying_progress": @{
            @(0): @"Verifying files: %d / %d...",
            @(1): @"Verificando arquivos: %d / %d...",
            @(2): @"Verificando archivos: %d / %d..."
        },
        @"tab_game": @{
            @(0): @"Game",
            @(1): @"Jogo",
            @(2): @"Juego"
        },
        @"tab_graphics": @{
            @(0): @"Graphics",
            @(1): @"Gráficos",
            @(2): @"Gráficos"
        },
        @"tab_controls": @{
            @(0): @"Controls",
            @(1): @"Controles",
            @(2): @"Controles"
        },
        @"tab_saves": @{
            @(0): @"Saves & Logs",
            @(1): @"Salves e Logs",
            @(2): @"Partidas y Registros"
        },
        @"tab_experimental": @{
            @(0): @"Experimental",
            @(1): @"Experimental",
            @(2): @"Experimental"
        },
        @"opt_resolution": @{
            @(0): @"Internal Resolution",
            @(1): @"Resolução Interna",
            @(2): @"Resolución Interna"
        },
        @"opt_resolution_desc": @{
            @(0): @"True 3D render target resolution (720p native, 540p or 480p performance)",
            @(1): @"Resolução interna real em 3D (720p nativo, 540p ou 480p desempenho)",
            @(2): @"Resolución de renderizado 3D real (720p nativo, 540p o 480p rendimiento)"
        },
        @"opt_fps_cap": @{
            @(0): @"Frame Rate Target",
            @(1): @"Alvo de Taxa de Quadros",
            @(2): @"Objetivo de Cuadros por Segundo"
        },
        @"opt_half_textures": @{
            @(0): @"Half-Resolution Textures",
            @(1): @"Texturas em Meia Resolução",
            @(2): @"Texturas a Media Resolución"
        },
        @"opt_half_textures_desc": @{
            @(0): @"Reduces VRAM pressure on 4GB-6GB devices by discarding top mipmap",
            @(1): @"Reduz pressão de VRAM em aparelhos de 4GB-6GB descartando o mipmap superior",
            @(2): @"Reduce el uso de VRAM en dispositivos de 4GB-6GB descartando el mipmap superior"
        },
        @"opt_low_ram": @{
            @(0): @"Low-RAM Texture Cache",
            @(1): @"Cache de Textura para Pouca RAM",
            @(2): @"Caché de Textura para Poca RAM"
        },
        @"opt_cpu_boost": @{
            @(0): @"CPU Boost / Fast-Core Pinning",
            @(1): @"Aceleração de CPU / Núcleos de Alto Desempenho",
            @(2): @"Aceleración de CPU / Núcleos de Alto Rendimiento"
        },
        @"opt_control_style": @{
            @(0): @"Touch Control Style",
            @(1): @"Estilo de Controle por Toque",
            @(2): @"Estilo de Control Táctil"
        },
        @"ctrl_xbox": @{
            @(0): @"Xbox 360 Gamepad",
            @(1): @"Controle Xbox 360",
            @(2): @"Mando Xbox 360"
        },
        @"ctrl_l4d2": @{
            @(0): @"L4D2 Mode (FPS Action + 5 Slots)",
            @(1): @"Modo L4D2 (Ação FPS + 5 Atalhos)",
            @(2): @"Modo L4D2 (Acción FPS + 5 Ranuras)"
        },
        @"opt_drag_look": @{
            @(0): @"Mobile Shooter Drag-to-Look",
            @(1): @"Arrastar para Olhar (Estilo FPS Mobile)",
            @(2): @"Deslizar para Mirar (Estilo FPS Móvil)"
        },
        @"opt_gyro_aim": @{
            @(0): @"Gyroscope Fine-Aim",
            @(1): @"Mira Fina com Giroscópio",
            @(2): @"Apuntado Fino con Giroscopio"
        },
        @"btn_layout_editor": @{
            @(0): @"Open Touch Layout Editor",
            @(1): @"Abrir Editor de Layout de Toque",
            @(2): @"Abrir Editor de Disposición Táctil"
        },
        @"btn_backup_saves": @{
            @(0): @"Backup Saves (.zip)",
            @(1): @"Fazer Backup dos Saves (.zip)",
            @(2): @"Respaldar Partidas (.zip)"
        },
        @"btn_restore_saves": @{
            @(0): @"Restore Saves (.zip)",
            @(1): @"Restaurar Saves (.zip)",
            @(2): @"Restaurar Partidas (.zip)"
        },
        @"btn_export_logs": @{
            @(0): @"Export Diagnostic Logs (.zip)",
            @(1): @"Exportar Logs de Diagnóstico (.zip)",
            @(2): @"Exportar Registros de Diagnóstico (.zip)"
        },
        @"opt_split_screen": @{
            @(0): @"2-Player Local Split Screen",
            @(1): @"Tela Dividida Local (2 Jogadores)",
            @(2): @"Pantalla Dividida Local (2 Jugadores)"
        },
        @"opt_dlc_installer": @{
            @(0): @"Install Xbox 360 DLC Package",
            @(1): @"Instalar Pacote de DLC do Xbox 360",
            @(2): @"Instalar Paquete de DLC de Xbox 360"
        },
        @"slot_1": @{
            @(0): @"Primary",
            @(1): @"Primária",
            @(2): @"Principal"
        },
        @"slot_2": @{
            @(0): @"Pistol/Melee",
            @(1): @"Pistola/Corpo a Corpo",
            @(2): @"Pistola/Cuerpo a Cuerpo"
        },
        @"slot_3": @{
            @(0): @"Grenade",
            @(1): @"Granada",
            @(2): @"Granada"
        },
        @"slot_4": @{
            @(0): @"Medkit",
            @(1): @"Kit Médico",
            @(2): @"Botiquín"
        },
        @"slot_5": @{
            @(0): @"Pills",
            @(1): @"Pílulas",
            @(2): @"Píldoras"
        },
        @"action_fire": @{
            @(0): @"FIRE",
            @(1): @"ATIRAR",
            @(2): @"DISPARAR"
        },
        @"action_shove": @{
            @(0): @"SHOVE",
            @(1): @"EMPURRÃO",
            @(2): @"EMPUJAR"
        },
        @"action_reload": @{
            @(0): @"RELOAD",
            @(1): @"RECARREGAR",
            @(2): @"RECARGAR"
        },
        @"action_jump": @{
            @(0): @"JUMP",
            @(1): @"PULAR",
            @(2): @"SALTAR"
        },
        @"action_crouch": @{
            @(0): @"CROUCH",
            @(1): @"AGACHO",
            @(2): @"AGANCHAR"
        },
        @"action_use": @{
            @(0): @"USE",
            @(1): @"USAR",
            @(2): @"USAR"
        },
        @"action_scope": @{
            @(0): @"ZOOM",
            @(1): @"ZOOM",
            @(2): @"ZOOM"
        },
        @"action_light": @{
            @(0): @"LIGHT",
            @(1): @"LANTERNA",
            @(2): @"LINTERNA"
        }
    };

    NSDictionary<NSNumber*, NSString*>* dict = strings[key];
    if (!dict) return key;

    NSNumber* langKey = @(static_cast<int>(lang));
    NSString* val = dict[langKey];
    return val ? val : dict[@(0)];
}

} // namespace l4d2::i18n

